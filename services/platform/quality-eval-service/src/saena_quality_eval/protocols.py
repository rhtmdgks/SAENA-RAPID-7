"""Adapter `typing.Protocol` interfaces for the external tools this engine's
gates ultimately depend on, plus pure-Python in-memory `Fake*` reference
implementations of each.

Mirrors `saena_domain.execution.protocols`'s discipline (shape only, no I/O)
and `saena_artifact_registry.blobstore.BlobStore`'s
Protocol-plus-in-memory-adapter pattern. Mission: "Protocol adapters (build
runner, test runner, scanners) with in-memory fakes — NO real builds/
subprocess in unit tests" — this module fixes the CALL SHAPE a real
subprocess-invoking adapter (build tool, pytest runner, secret/security
scanner, `diff-cover`) would satisfy in a later patch unit; every adapter
this module itself ships is a `Fake*` that returns a caller-supplied, fully
deterministic outcome — never a real subprocess, network call, or
filesystem read. `saena_quality_eval.gates` never imports this module: gate
functions take the already-produced outcome dataclass directly, keeping the
gate layer pure regardless of which adapter (fake today, real in a later
unit) produced it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from saena_quality_eval.inputs import (
    BuildOutcome,
    CoverageReport,
    GeneratedCodeDriftOutcome,
    SecretScanOutcome,
    SecurityScanOutcome,
    TestOutcome,
)


@runtime_checkable
class BuildRunner(Protocol):
    """Runs the customer repo's official build command."""

    def run_build(self) -> BuildOutcome: ...


@runtime_checkable
class TestRunner(Protocol):
    """Runs a named test suite (`"unit"`, `"integration"`, `"regression"`, ...).

    NOTE: deliberately does NOT set `__test__ = False` the way
    `inputs.TestOutcome` does to silence pytest's collection warning for
    this class — `typing.Protocol`'s `runtime_checkable` `isinstance` check
    is STRUCTURAL (computed from every class-body attribute, dunders
    excluded per `typing`'s own exclusion list), and `__test__` is NOT on
    that exclusion list: adding it here would silently make `__test__` part
    of this Protocol's required structural surface, breaking `isinstance(
    FakeTestRunner(...), TestRunner)` for any adapter that does not also
    define `__test__`. The harmless `PytestCollectionWarning` this class
    triggers (`"cannot collect test class 'TestRunner' because it has a
    __init__ constructor"`) is accepted here rather than risking that.
    """

    def run_tests(self, suite: str) -> TestOutcome: ...


@runtime_checkable
class SecurityScanner(Protocol):
    """Runs the Algorithm §11.1 security sweep (secret leak / injection
    propagation / supply-chain anomaly detection)."""

    def scan(self) -> SecurityScanOutcome: ...


@runtime_checkable
class SecretScanner(Protocol):
    """Runs this package's own dedicated secret-scan pass over the patch
    content (mission item 6)."""

    def scan(self) -> SecretScanOutcome: ...


@runtime_checkable
class GeneratedCodeDriftScanner(Protocol):
    """Regenerates every codegen output path and diffs it against the
    committed content (mission item 7)."""

    def scan(self) -> GeneratedCodeDriftOutcome: ...


@runtime_checkable
class CoverageReporter(Protocol):
    """Produces a changed-line coverage report (diff-cover-shaped, ADR-0017)."""

    def report(self) -> CoverageReport: ...


class FakeBuildRunner:
    """Returns a caller-supplied, fixed `BuildOutcome` — never invokes a
    real build command."""

    def __init__(self, outcome: BuildOutcome) -> None:
        self._outcome = outcome

    def run_build(self) -> BuildOutcome:
        return self._outcome


class FakeTestRunner:
    """Returns a caller-supplied `TestOutcome` per suite name, keyed by the
    `suite` argument — never invokes a real test process."""

    def __init__(self, outcomes_by_suite: dict[str, TestOutcome]) -> None:
        self._outcomes_by_suite = dict(outcomes_by_suite)

    def run_tests(self, suite: str) -> TestOutcome:
        try:
            return self._outcomes_by_suite[suite]
        except KeyError as exc:
            raise KeyError(f"FakeTestRunner has no configured outcome for suite {suite!r}") from exc


class FakeSecurityScanner:
    def __init__(self, outcome: SecurityScanOutcome) -> None:
        self._outcome = outcome

    def scan(self) -> SecurityScanOutcome:
        return self._outcome


class FakeSecretScanner:
    def __init__(self, outcome: SecretScanOutcome) -> None:
        self._outcome = outcome

    def scan(self) -> SecretScanOutcome:
        return self._outcome


class FakeGeneratedCodeDriftScanner:
    def __init__(self, outcome: GeneratedCodeDriftOutcome) -> None:
        self._outcome = outcome

    def scan(self) -> GeneratedCodeDriftOutcome:
        return self._outcome


class FakeCoverageReporter:
    def __init__(self, report: CoverageReport) -> None:
        self._report = report

    def report(self) -> CoverageReport:
        return self._report


__all__ = [
    "BuildRunner",
    "CoverageReporter",
    "FakeBuildRunner",
    "FakeCoverageReporter",
    "FakeGeneratedCodeDriftScanner",
    "FakeSecretScanner",
    "FakeSecurityScanner",
    "FakeTestRunner",
    "GeneratedCodeDriftScanner",
    "SecretScanner",
    "SecurityScanner",
    "TestRunner",
]
