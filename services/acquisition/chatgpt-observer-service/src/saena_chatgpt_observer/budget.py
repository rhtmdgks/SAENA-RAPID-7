"""`ObservationBudget` — `JobKind.CHATGPT_OBSERVER`'s rate/timeout envelope.

Same derivation discipline as `saena_site_discovery.budget.crawl_budget_for`
(that module's docstring applies verbatim, substituting "route" for
"query") — every field derives from `resource_limits_for`, this package's
own further mapping from those 4 generic fields to observation-specific
concepts is this patch unit's own reasoned proposal, NOT confirmed ops
config.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.execution import JobKind, resource_limits_for

from saena_chatgpt_observer.errors import JobKindScopeError

# Heuristic: 1 MiB of the kind's `max_artifact_mib` budget funds roughly one
# captured observation session (screenshot + extracted citations) —
# deliberately conservative and documented, not a measured figure.
_MIB_PER_QUERY = 1
_TIMEOUT_DIVISOR = 10
_MIN_REQUEST_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class ObservationBudget:
    """`JobKind.CHATGPT_OBSERVER`'s rate/timeout/resource envelope for one
    observation run."""

    max_queries_per_run: int
    request_timeout_seconds: float
    max_retries: int
    active_deadline_seconds: int


def observation_budget_for(kind: JobKind) -> ObservationBudget:
    """Return the `ObservationBudget` derived from `resource_limits_for(kind)`.

    Raises `JobKindScopeError` for any `kind` other than
    `JobKind.CHATGPT_OBSERVER`.
    """
    if kind is not JobKind.CHATGPT_OBSERVER:
        raise JobKindScopeError(
            f"saena_chatgpt_observer only serves JobKind.CHATGPT_OBSERVER, got {kind!r}",
            context={"job_kind": str(kind)},
        )
    limits = resource_limits_for(kind)
    return ObservationBudget(
        max_queries_per_run=limits.max_artifact_mib * _MIB_PER_QUERY,
        request_timeout_seconds=max(
            limits.active_deadline_seconds / _TIMEOUT_DIVISOR, _MIN_REQUEST_TIMEOUT_SECONDS
        ),
        max_retries=limits.max_retries,
        active_deadline_seconds=limits.active_deadline_seconds,
    )


__all__ = ["ObservationBudget", "observation_budget_for"]
