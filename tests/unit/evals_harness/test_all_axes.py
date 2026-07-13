"""CI-blocking entrypoint (w3-10 mission): every fixture under every one of
the 9 mandatory eval axes must score exactly as its fixture declares.

This module (like every module in `tests/unit/evals_harness/`) runs in the
BLOCKING unit lane: it lives under `tests/unit/**`, not `tests/integration/
**`, so it is never auto-marked `pytest.mark.integration`
(`tests/integration/conftest.py`'s `pytest_collection_modifyitems` is
path-scoped to `tests/integration/**` only) and is collected + required by
both `just test` (`pytest -m "not integration"`) and CI's `unit` job — no
container, no real external process, fully deterministic and fast.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from harness_paths import AXIS_FIXTURE_DIRS

from evals.engine.fixture import Fixture, load_fixtures
from evals.engine.result import FixtureOutcome
from evals.engine.runner import run_fixture
from evals.engine.scorers import AXIS_SCORERS, MANDATORY_AXES


def _all_fixtures() -> list[Fixture]:
    fixtures: list[Fixture] = []
    for directory in AXIS_FIXTURE_DIRS.values():
        fixtures.extend(load_fixtures(directory))
    return fixtures


_ALL_FIXTURES = _all_fixtures()


def test_at_least_nine_axes_are_registered() -> None:
    assert MANDATORY_AXES.issubset(AXIS_SCORERS)
    assert len(MANDATORY_AXES) >= 9


def test_every_mandatory_axis_has_a_fixture_directory_with_fixtures() -> None:
    for axis in MANDATORY_AXES:
        directory = AXIS_FIXTURE_DIRS[axis]
        fixtures = load_fixtures(directory)
        assert fixtures, f"axis {axis!r} ({directory}) has no fixtures"


def test_every_fixture_names_a_registered_axis() -> None:
    for fixture in _ALL_FIXTURES:
        assert fixture.axis in AXIS_SCORERS, (
            f"{fixture.source_path}: axis {fixture.axis!r} is not a registered scorer"
        )


def test_fixture_ids_are_unique_within_their_axis() -> None:
    seen: dict[str, set[str]] = {}
    for fixture in _ALL_FIXTURES:
        ids = seen.setdefault(fixture.axis, set())
        assert fixture.fixture_id not in ids, (
            f"duplicate fixture_id {fixture.fixture_id!r} in axis {fixture.axis!r}"
        )
        ids.add(fixture.fixture_id)


def _fixture_case_id(fixture: Fixture) -> str:
    return f"{fixture.axis}/{fixture.fixture_id}"


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=_fixture_case_id)
def test_fixture_matches_expectation(fixture: Fixture) -> None:
    scorer = AXIS_SCORERS[fixture.axis]
    outcome: FixtureOutcome = run_fixture(fixture, scorer)
    assert outcome.threshold_consistent, (
        f"{fixture.fixture_id}: scorer passed={outcome.result.passed} is inconsistent with "
        f"score={outcome.result.score} vs threshold={fixture.threshold}"
    )
    assert outcome.matched_expected_passed, (
        f"{fixture.fixture_id}: expected passed={fixture.expected_passed}, got "
        f"{outcome.result.passed} (reasons={outcome.result.reasons})"
    )
    assert outcome.matched_expected_score, (
        f"{fixture.fixture_id}: expected score={fixture.expected_score}, got {outcome.result.score}"
    )
    assert outcome.ok


def test_reproducibility_of_the_harness_itself() -> None:
    """Running every fixture TWICE in the same process produces byte-for-byte
    identical `ScoreResult`s — the harness is itself deterministic (no
    fixture ever touches wall-clock or randomness)."""
    for fixture in _ALL_FIXTURES:
        scorer = AXIS_SCORERS[fixture.axis]
        first = run_fixture(fixture, scorer)
        second = run_fixture(fixture, scorer)
        assert first.result == second.result, (
            f"{fixture.fixture_id}: scorer produced different results on repeated calls "
            "with the same fixture"
        )


def test_every_axis_has_at_least_one_discriminating_fixture() -> None:
    """Mission requirement: "include false-positive AND false-negative
    example fixtures for at least a few axes ... proving the scorer
    discriminates". Every one of the 9 mandatory axes in this harness
    carries at least one `false_positive_guard` AND one `false_negative_guard`
    fixture (exceeding the "a few axes" minimum)."""
    tags_by_axis: dict[str, set[str]] = {}
    for fixture in _ALL_FIXTURES:
        tags_by_axis.setdefault(fixture.axis, set()).add(fixture.tag)

    axes_missing_fp = [
        axis
        for axis in MANDATORY_AXES
        if "false_positive_guard" not in tags_by_axis.get(axis, set())
    ]
    axes_missing_fn = [
        axis
        for axis in MANDATORY_AXES
        if "false_negative_guard" not in tags_by_axis.get(axis, set())
    ]
    assert not axes_missing_fp, f"axes with no false_positive_guard fixture: {axes_missing_fp}"
    assert not axes_missing_fn, f"axes with no false_negative_guard fixture: {axes_missing_fn}"


def test_fixture_directories_are_covered_by_conftest_registry(
    axis_fixture_dirs: dict[str, Path],
) -> None:
    assert axis_fixture_dirs == AXIS_FIXTURE_DIRS
