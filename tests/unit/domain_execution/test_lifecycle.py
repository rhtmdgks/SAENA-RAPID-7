"""Job lifecycle state machine — every legal edge, every illegal edge,
duplicate-transition idempotency, terminal-state dead ends."""

from __future__ import annotations

import itertools

import pytest
from saena_domain.execution.errors import InvalidJobTransitionError
from saena_domain.execution.lifecycle import (
    TERMINAL_STATUSES,
    JobStatus,
    JobTransitionOutcome,
    is_terminal,
    transition,
)

_LEGAL_EDGES: set[tuple[JobStatus, JobStatus]] = {
    (JobStatus.PENDING, JobStatus.RUNNING),
    (JobStatus.PENDING, JobStatus.CANCELLED),
    (JobStatus.RUNNING, JobStatus.SUCCEEDED),
    (JobStatus.RUNNING, JobStatus.FAILED),
    (JobStatus.RUNNING, JobStatus.CANCELLED),
    (JobStatus.RUNNING, JobStatus.TIMED_OUT),
}


@pytest.mark.parametrize(("current", "target"), sorted(_LEGAL_EDGES))
def test_legal_edges_change_state(current: JobStatus, target: JobStatus) -> None:
    outcome = transition(current, target)
    assert outcome == JobTransitionOutcome(status=target, changed=True)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (c, t)
        for c, t in itertools.product(JobStatus, JobStatus)
        if c != t and (c, t) not in _LEGAL_EDGES
    ],
)
def test_illegal_edges_raise(current: JobStatus, target: JobStatus) -> None:
    with pytest.raises(InvalidJobTransitionError) as excinfo:
        transition(current, target)
    assert excinfo.value.current == current
    assert excinfo.value.target == target
    assert excinfo.value.error_code == "saena.execution.invalid_transition"


@pytest.mark.parametrize("status", list(JobStatus))
def test_same_state_request_is_an_idempotent_no_op(status: JobStatus) -> None:
    """Duplicate-transition idempotency semantics: requesting the CURRENT
    status again — including terminal-to-same-terminal — never raises and
    is reported as `changed=False`, absorbing at-least-once redelivery of a
    status update without the caller needing to pre-check for a replay."""
    outcome = transition(status, status)
    assert outcome == JobTransitionOutcome(status=status, changed=False)


def test_terminal_statuses_set_matches_dead_end_adjacency() -> None:
    assert {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.TIMED_OUT,
    } == TERMINAL_STATUSES
    for status in TERMINAL_STATUSES:
        assert is_terminal(status)
    assert not is_terminal(JobStatus.PENDING)
    assert not is_terminal(JobStatus.RUNNING)


@pytest.mark.parametrize("terminal_status", sorted(TERMINAL_STATUSES))
def test_no_transition_out_of_a_terminal_status_to_a_different_status(
    terminal_status: JobStatus,
) -> None:
    for target in JobStatus:
        if target == terminal_status:
            continue
        with pytest.raises(InvalidJobTransitionError):
            transition(terminal_status, target)
