"""Policy/authz error hierarchy for saena_domain.policy and saena_domain.authz."""

from __future__ import annotations


class PolicyViolationError(Exception):
    """Base class for all saena_domain.policy violations."""


class InvalidTransitionError(PolicyViolationError):
    """Raised when a requested PlanState transition is not permitted."""

    def __init__(self, current_state: object, requested_decision: object) -> None:
        self.current_state = current_state
        self.requested_decision = requested_decision
        super().__init__(
            f"invalid transition: cannot apply {requested_decision!r} from state {current_state!r}"
        )


class ExecutionBlockedError(PolicyViolationError):
    """Raised by guard_execution when a plan may not proceed to execution."""


class ContractHashViolationError(PolicyViolationError):
    """Raised when a plan is mutated/re-proposed after approval under the same
    contract_hash but with different content (post-approval immutability, H-3/H-7)."""


class InconsistentPlanSnapshotError(PolicyViolationError):
    """Raised when transition() receives exactly one of stored_plan/
    presented_plan. Both-or-neither are the only legal states: supplying only
    one would silently skip the guard_immutability choke point (fail-open),
    so this module fails closed instead of treating a partial snapshot pair
    as "no immutability check requested" (critic MUST-FIX 1 re-verify)."""


class ConflictingDecisionError(PolicyViolationError):
    """Raised when two non-identical ApprovalDecision instances are submitted
    for the same (contract_hash, approver_actor_id) idempotency key."""
