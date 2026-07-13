"""`ScoreResult` (a scorer's pure output) and `FixtureOutcome` (the
harness's own verdict: does the scorer's actual result match what the
fixture declared it must produce)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """The pure output of one `scorers.<axis>.score(fixture)` call.

    `passed` and `score` are independently asserted by the harness against
    the fixture — a scorer is free to compute `score` as a fraction (e.g.
    `2/3` for a multi-claim evidence check) while `passed` applies the
    fixture's own `threshold`; `reasons` is a tuple of human-readable
    strings explaining every check that failed (empty when `passed=True`
    for every axis in this harness — see each scorer's own module).
    """

    passed: bool
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FixtureOutcome:
    """The harness's verdict for one fixture: did the scorer's actual
    `ScoreResult` match what the fixture declared as `expected_passed`/
    `expected_score`, and is `passed` internally consistent with `score`
    vs. the fixture's own `threshold`?"""

    fixture_id: str
    axis: str
    tag: str
    result: ScoreResult
    expected_passed: bool
    expected_score: float
    threshold: float

    @property
    def matched_expected_passed(self) -> bool:
        return self.result.passed == self.expected_passed

    @property
    def matched_expected_score(self) -> bool:
        return abs(self.result.score - self.expected_score) < 1e-9

    @property
    def threshold_consistent(self) -> bool:
        """`True` iff the scorer's own `passed` verdict agrees with
        comparing its `score` against the fixture's declared `threshold`
        — catches a scorer that reports `passed=True` with a `score` below
        its own stated bar, or vice versa."""
        return (self.result.score >= self.threshold) == self.result.passed

    @property
    def ok(self) -> bool:
        """`True` iff this fixture ran exactly as declared: the scorer's
        `passed`/`score` matched the fixture's expectation AND was
        internally threshold-consistent."""
        return (
            self.matched_expected_passed
            and self.matched_expected_score
            and self.threshold_consistent
        )


__all__ = ["FixtureOutcome", "ScoreResult"]
