"""`run_fixture`/`run_axis`/`run_directory` — pure execution of fixtures
against scorer functions.

No wall-clock, no randomness, no I/O beyond the fixture loading `directory`
callers hand in (this module itself performs none). Given the same
`(fixture, scorer)` pair, `run_fixture` returns a byte-identical
`FixtureOutcome` on every call.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from evals.engine.fixture import Fixture, load_fixtures
from evals.engine.result import FixtureOutcome, ScoreResult

Scorer = Callable[[Fixture], ScoreResult]


def run_fixture(fixture: Fixture, scorer: Scorer) -> FixtureOutcome:
    """Score one fixture and wrap the result with the fixture's own
    expectation, ready for `FixtureOutcome.ok` assertion."""
    result = scorer(fixture)
    return FixtureOutcome(
        fixture_id=fixture.fixture_id,
        axis=fixture.axis,
        tag=fixture.tag,
        result=result,
        expected_passed=fixture.expected_passed,
        expected_score=fixture.expected_score,
        threshold=fixture.threshold,
    )


def run_axis(fixtures: list[Fixture], scorer: Scorer) -> list[FixtureOutcome]:
    return [run_fixture(fixture, scorer) for fixture in fixtures]


def run_directory(directory: Path, scorer: Scorer) -> list[FixtureOutcome]:
    """Load every fixture under `directory` and score it — the CI-blocking
    entrypoint each `tests/unit/evals_harness/test_axis_*.py` module calls."""
    return run_axis(load_fixtures(directory), scorer)


__all__ = ["Scorer", "run_axis", "run_directory", "run_fixture"]
