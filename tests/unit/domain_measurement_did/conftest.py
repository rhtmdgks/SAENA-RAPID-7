"""Shared fixtures for the w5-05 deterministic DiD engine tests.

Every fixture here is SYNTHETIC — no customer data, no I/O. The policy
fixture is TEST-ONLY (provenance ``test_fixture`` from the closed
``PolicyProvenance`` vocabulary): the production ``min_repeats`` /
``effect_threshold`` values are BLOCKED-human per wave5-plan.md E6 (GRS) and
the w5-05 mission, so no fixture in this suite pretends to be a production
policy.
"""

from __future__ import annotations

from datetime import UTC, datetime

from saena_domain.measurement.did import (
    CellObservation,
    DiDPolicy,
    SignalSeries,
)

#: Canonical measurement window used by the fixtures below. Observations
#: whose timestamp falls outside [window_start, window_end] must be flagged
#: ``late_observation`` and excluded from the cell aggregate.
WINDOW_START = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 8, 0, 0, 0, tzinfo=UTC)

IN_WINDOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=UTC)
LATE = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def make_policy(min_repeats: int = 3, effect_threshold: float = 1.0) -> DiDPolicy:
    """A TEST-ONLY DiD policy. Never a production value (see module docstring)."""
    return DiDPolicy(
        min_repeats=min_repeats,
        effect_threshold=effect_threshold,
        provenance="test_fixture",
    )


def cell(value: float, *, repeats: int = 3, at: datetime = IN_WINDOW) -> CellObservation:
    """A 2x2 cell whose ``repeats`` repeat-observations each equal ``value``.

    Equal-repeat cell → mean == value, sample_count == repeats. Used by the
    synthetic-effect fixtures so the recovered lift is exact.
    """
    return CellObservation(repeat_values=(value,) * repeats, timestamps=(at,) * repeats)


def series(
    *,
    baseline_treatment: CellObservation | None,
    baseline_control: CellObservation | None,
    post_treatment: CellObservation | None,
    post_control: CellObservation | None,
    metric_id: str = "citation_count",
    layer: str = "citation",
    evidence_basis_id: str = "eb-001",
) -> SignalSeries:
    return SignalSeries(
        layer=layer,
        metric_id=metric_id,
        evidence_basis_id=evidence_basis_id,
        baseline_treatment=baseline_treatment,
        baseline_control=baseline_control,
        post_treatment=post_treatment,
        post_control=post_control,
    )
