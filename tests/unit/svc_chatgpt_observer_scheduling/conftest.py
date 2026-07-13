"""Shared fixtures for the w5-15 measurement-scheduling unit lane.

`saena-chatgpt-observer` is a registered workspace member, so it imports
normally (no sys.path hack). Everything here is deterministic + offline — a
TEST-ONLY `RatePolicy` fixture (NO production values; see wave5-plan.md H2:
production rate/quota/imbalance policy is BLOCKED(human)), a complete
registered `ObservationCell`, and an aligned `MeasurementWindow`.
"""

from __future__ import annotations

import pytest
from saena_chatgpt_observer.measurement_scheduling import (
    MeasurementWindow,
    ObservationCell,
    RatePolicy,
)

# One day, in seconds — window/rate arithmetic reference.
DAY_S = 86_400


@pytest.fixture
def cell() -> ObservationCell:
    """A COMPLETE registered cell — every field bound upstream (w5-04)."""
    return ObservationCell(
        query_cluster_ref="cluster://acme/onboarding",
        locale="en-US",
        browser_policy="headless-clean",
        repeat_count=4,
        domain_key="chat.openai.com",
    )


@pytest.fixture
def window() -> MeasurementWindow:
    """A 1-day window starting at an arbitrary fixed epoch (deterministic —
    no wall-clock)."""
    start = 1_700_000_000
    return MeasurementWindow(start_epoch_s=start, end_epoch_s=start + DAY_S)


@pytest.fixture
def policy() -> RatePolicy:
    """TEST-ONLY rate policy fixture — every value injected, none is a
    production figure. Loose enough to admit the fixture cell's schedule.
    imbalance_ratio_cap=2.0 admits the round-robin off-by-one for odd totals."""
    return RatePolicy(
        max_per_day=1_000,
        max_concurrent=3,
        min_gap_seconds=60,
        backoff_base_seconds=2,
        backoff_factor=2,
        backoff_cap_seconds=30,
        max_retries=4,
        imbalance_ratio_cap=2.0,
    )
