"""Job lifecycle state machine — `JobStatus` + pure `transition()`.

```
PENDING -> RUNNING -> SUCCEEDED
                    -> FAILED
                    -> CANCELLED
                    -> TIMED_OUT
PENDING -> CANCELLED   (cancelled before the Job pod ever starts running)
```

Mirrors `saena_domain.policy.transitions`'s style: `_ALLOWED_TRANSITIONS`
(an adjacency dict) is the single source of truth, `transition()` is pure
(no I/O, no hidden state, same inputs always produce the same output), and
every terminal state is a dead end (empty adjacency set) — exactly
`saena_domain.policy.states`/`transitions`'s `PlanState`/`_ALLOWED_TRANSITIONS`
shape, applied to the Wave 3 job lifecycle instead of the ChangePlan approval
lifecycle.

**Duplicate-transition idempotency semantics** (task instruction): requesting
the CURRENT status again (`target == current`) is always a no-op —
`transition()` returns `JobTransitionOutcome(status=current, changed=False)`
rather than raising, for EVERY status including terminal-to-same-terminal.
This matters because job status updates typically arrive over an
at-least-once event/Temporal-signal path (ADR-0013 envelope
`idempotency_key`, `api-event-contracts.md` at-least-once delivery): a
duplicate delivery of "job X succeeded" must never be treated as an illegal
SUCCEEDED->SUCCEEDED edge, and a caller does not need to pre-check "is this a
replay?" before calling `transition()` — the function itself absorbs the
replay case. Any OTHER `(current, target)` pair not in
`_ALLOWED_TRANSITIONS[current]` raises `InvalidJobTransitionError` —
including moving from a terminal state to any DIFFERENT status (terminal
states have an empty adjacency set, so every `target != current` from a
terminal `current` is rejected).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from saena_domain.execution.errors import InvalidJobTransitionError


class JobStatus(StrEnum):
    """Wave 3 job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMED_OUT,
        }
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.TIMED_OUT: frozenset(),
}

TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.TIMED_OUT,
    }
)


@dataclass(frozen=True, slots=True)
class JobTransitionOutcome:
    """Result of `transition()`: the resulting status plus whether it
    actually changed (`changed=False` on an idempotent same-state replay,
    the ONLY case where `status == status` going in and coming out does not
    imply an error)."""

    status: JobStatus
    changed: bool


def transition(current: JobStatus, target: JobStatus) -> JobTransitionOutcome:
    """Compute the outcome of moving `current` towards `target`.

    - `target == current`: idempotent no-op, `changed=False` (see module
      docstring).
    - `target` reachable from `current` per `_ALLOWED_TRANSITIONS`:
      `JobTransitionOutcome(status=target, changed=True)`.
    - anything else (illegal edge, including any transition attempted from a
      terminal `current`): raises `InvalidJobTransitionError`.
    """
    if target == current:
        return JobTransitionOutcome(status=current, changed=False)
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidJobTransitionError(current, target)
    return JobTransitionOutcome(status=target, changed=True)


def is_terminal(status: JobStatus) -> bool:
    """True iff `status` has no outgoing transitions."""
    return status in TERMINAL_STATUSES


__all__ = [
    "TERMINAL_STATUSES",
    "JobStatus",
    "JobTransitionOutcome",
    "is_terminal",
    "transition",
]
