"""Structured result types shared by every preflight check and the CLI.

`CheckResult` is deliberately not an exception-based design: k3s spec §8.1
lists six independent fail conditions and the CLI report must name *every*
one that failed in a single run, not stop at the first raised exception.
Each check function therefore always returns a `CheckResult` — pass or
fail — and `PreflightReport` aggregates the full set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The outcome of a single preflight check.

    Attributes:
        name: stable machine-readable check identifier (e.g.
            `"engine_flags"`) — used as the JSON key and referenced by
            `--json` consumers/CI, never reworded across releases.
        passed: `True` iff the check found no k3s spec §8.1 fail condition.
        detail: human-readable explanation. For a failing check this names
            the *specific* violation (e.g. which engine flag was on, which
            secret ref resolved to plaintext) rather than a generic
            "failed" — CI logs and operators both need to act on this
            without re-reading the values file by hand.
        context: structured, log-safe data about the violation (or, for a
            passing check, a short evidence summary) — mirrors the
            `error_code`/`context` convention used by
            `saena_engine_gateway.errors` elsewhere in this repo. Never
            secret material — checks that touch secret *references* record
            the reference key/path, never a resolved value.
    """

    name: str
    passed: bool
    detail: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "context": self.context,
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """The full result of one `forgectl preflight` run — every check's
    `CheckResult`, in the fixed order §8.1 lists them."""

    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """`True` iff every check passed. An empty `checks` tuple is
        vacuously *not* a pass — `PreflightReport` is always constructed
        from the fixed six-check set, so an empty tuple only ever occurs
        via a construction bug, and fail-closed is the safer default for
        that case."""
        return len(self.checks) > 0 and all(check.passed for check in self.checks)

    @property
    def failed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "failed_check_names": [check.name for check in self.failed_checks],
        }
