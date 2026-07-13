"""`CrawlBudget` — `JobKind.SITE_DISCOVERY`'s rate/timeout/resource envelope.

Derives every field from `saena_domain.execution.resource_limits_for`
(this package's own required import per the founding unit's task
instruction) rather than inventing a second, disconnected budget config —
`ResourceLimits`' own module docstring already documents that the 4
non-`AGENT_RUNNER` `JobKind`s' numbers are this module's (w3-01's) own
reasoned proposal, NOT confirmed ops config; the derivation below is this
patch unit's OWN further reasoned mapping from those 4 generic fields to
crawl-specific concepts (route count / per-request timeout), likewise NOT
confirmed ops config — a later unit reconciling `site-discovery-service`'s
own Helm values section should revisit both layers together, not just this
one.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.execution import JobKind, resource_limits_for

from saena_site_discovery.errors import JobKindScopeError

# Heuristic: 1 MiB of the kind's `max_artifact_mib` budget funds roughly one
# inventoried route's worth of captured evidence (page snapshot + extracted
# metadata) — deliberately conservative and documented, not a measured
# figure (see module docstring).
_MIB_PER_ROUTE = 1
# A single route's fetch gets a small, bounded slice of the whole run's
# deadline — no single slow/hanging route may consume the entire
# `active_deadline_seconds` budget on its own.
_TIMEOUT_DIVISOR = 20
_MIN_REQUEST_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class CrawlBudget:
    """`JobKind.SITE_DISCOVERY`'s rate/timeout/resource envelope for one
    discovery run."""

    max_routes_per_run: int
    request_timeout_seconds: float
    max_retries: int
    active_deadline_seconds: int


def crawl_budget_for(kind: JobKind) -> CrawlBudget:
    """Return the `CrawlBudget` derived from `resource_limits_for(kind)`.

    Raises `JobKindScopeError` for any `kind` other than
    `JobKind.SITE_DISCOVERY` — this service exists to serve that one
    `JobKind` only (mirrors `guard_engine_id`'s "is this even permitted at
    all" shape, applied to job-kind scope rather than engine-id scope).
    """
    if kind is not JobKind.SITE_DISCOVERY:
        raise JobKindScopeError(
            f"saena_site_discovery only serves JobKind.SITE_DISCOVERY, got {kind!r}",
            context={"job_kind": str(kind)},
        )
    limits = resource_limits_for(kind)
    return CrawlBudget(
        max_routes_per_run=limits.max_artifact_mib * _MIB_PER_ROUTE,
        request_timeout_seconds=max(
            limits.active_deadline_seconds / _TIMEOUT_DIVISOR, _MIN_REQUEST_TIMEOUT_SECONDS
        ),
        max_retries=limits.max_retries,
        active_deadline_seconds=limits.active_deadline_seconds,
    )


__all__ = ["CrawlBudget", "crawl_budget_for"]
