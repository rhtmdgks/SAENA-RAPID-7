"""`run_site_discovery` — the `JobKind.SITE_DISCOVERY` read-only crawl pass.

W3 MINIMAL scope (explicit non-goals, per this unit's own task instruction):
this module does NOT implement a real crawler/browser-pool client (W4), does
NOT do any intelligence/recommendation/scoring over the captured records,
and NEVER writes to or mutates the site/repo it inventories — every fact
below is captured through `crawler.SiteCrawlerPort`, a structurally
read-only Protocol (see that module's docstring).

Pipeline per route, in order:

1. `crawler.check_robots(route)` — the robots/policy boundary hook. A
   disallow (`allowed=False`) means the route is recorded as
   `robots_allowed=False` and `fetch_route` is NEVER called for it — this
   is deliverable 3's "respect a disallow ⇒ skip + record, never fetch"
   requirement, enforced here as a hard `if`/`continue` before any fetch
   call, not a best-effort convention.
2. `crawler.fetch_route(route)` (allowed routes only) — wrapped in a bounded
   retry loop (`CrawlBudget.max_retries`, from `resource_limits_for`) that
   catches `TransientFetchError` only; any other exception propagates
   immediately (never silently retried).
3. An `AuditEntry` is appended for EVERY route (fetched or skipped) —
   deliverable 4's "audit trail per observation".

Before the loop starts, the whole run is bounds-checked against
`CrawlBudget.max_routes_per_run` (deliverable 3's rate limit) and, during
the loop, against `CrawlBudget.active_deadline_seconds` via an injectable
`clock` (deliverable 3's timeout) — both raise a typed, retryable
`SiteDiscoveryError` subclass rather than silently truncating the run.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from saena_domain.execution import (
    JobContext,
    JobError,
    JobKind,
    JobStatus,
    build_site_inventory_completed_payload,
    transition,
)

from saena_site_discovery.budget import CrawlBudget, crawl_budget_for
from saena_site_discovery.crawler import SiteCrawlerPort, TransientFetchError
from saena_site_discovery.errors import (
    CrawlBudgetExceededError,
    CrawlDeadlineExceededError,
    CrawlRetryExhaustedError,
)
from saena_site_discovery.records import ContentRecordProjection, RenderMode


def _utc_now_iso() -> str:
    """Render the current UTC instant in the `TimestampUtc` contract shape
    (`^[0-9]{4}-...Z$`, `packages/schemas` `site_context_v1.TimestampUtc`)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One audit-trail line for a single route decision within a discovery
    run — deliverable 4 ("audit trail per observation"), carries
    `JobContext`'s tenant/actor identity (ADR-0014) directly rather than a
    bare string, so a consumer never has to re-derive "who ran this"."""

    tenant_id: str
    actor_id: str
    run_id: str
    route_path: str
    action: str  # "fetched" | "skipped_robots_disallowed"
    detail: JobError | None
    recorded_at: str


@dataclass(frozen=True, slots=True)
class SiteInventoryObservation:
    """Immutable, frozen site-inventory observation artifact (deliverable
    2). `records` never carries raw fetched content — each
    `ContentRecordProjection.evidence_ref` is an opaque reference only (see
    that module's docstring)."""

    job_context: JobContext
    site_id: str
    inventory_version: str
    records: tuple[ContentRecordProjection, ...]
    audit_trail: tuple[AuditEntry, ...]
    captured_at: str


@dataclass(frozen=True, slots=True)
class SiteDiscoveryRunResult:
    """`run_site_discovery`'s return value: the captured observation, the
    `site.inventory.completed.v1` event payload built for it (deliverable
    6), and the run's final `JobStatus`."""

    observation: SiteInventoryObservation
    event_payload: dict[str, Any]
    final_status: JobStatus


def _fetch_with_retries(
    crawler: SiteCrawlerPort, route_path: str, *, max_retries: int
) -> ContentRecordProjection:
    attempt = 0
    while True:
        try:
            fetched = crawler.fetch_route(route_path)
        except TransientFetchError:
            attempt += 1
            if attempt > max_retries:
                raise CrawlRetryExhaustedError(
                    f"route {route_path!r} exceeded {max_retries} retries",
                    context={"route_path": route_path, "max_retries": max_retries},
                ) from None
            continue
        return ContentRecordProjection(
            route_path=route_path,
            render_mode=fetched.render_mode,
            robots_allowed=True,
            canonical_url=fetched.canonical_url,
            sitemap_listed=fetched.sitemap_listed,
            structured_data_present=fetched.structured_data_present,
            evidence_ref=fetched.evidence_ref,
            observed_at=_utc_now_iso(),
        )


def run_site_discovery(
    *,
    job_context: JobContext,
    crawler: SiteCrawlerPort,
    site_id: str,
    inventory_version: str,
    routes: Sequence[str],
    budget: CrawlBudget | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SiteDiscoveryRunResult:
    """Run one read-only `JobKind.SITE_DISCOVERY` inventory pass over
    `routes` and return the captured `SiteDiscoveryRunResult`.

    `budget` defaults to `crawl_budget_for(JobKind.SITE_DISCOVERY)`; a
    caller may inject an override only for testing this function's own
    budget-enforcement branches deterministically (`clock` is always
    injectable for the same reason — no real wall-clock sleep ever happens
    in this package's unit tests).
    """
    effective_budget = budget if budget is not None else crawl_budget_for(JobKind.SITE_DISCOVERY)

    if len(routes) > effective_budget.max_routes_per_run:
        raise CrawlBudgetExceededError(
            f"{len(routes)} routes requested exceeds this run's budget of "
            f"{effective_budget.max_routes_per_run}",
            context={
                "requested_routes": len(routes),
                "max_routes_per_run": effective_budget.max_routes_per_run,
            },
        )

    status = JobStatus.PENDING
    status = transition(status, JobStatus.RUNNING).status

    started_at = clock()
    records: list[ContentRecordProjection] = []
    audit_trail: list[AuditEntry] = []

    def _audit(route_path: str, action: str, detail: JobError | None) -> None:
        audit_trail.append(
            AuditEntry(
                tenant_id=job_context.tenant_id,
                actor_id=job_context.actor_id,
                run_id=job_context.run_id,
                route_path=route_path,
                action=action,
                detail=detail,
                recorded_at=_utc_now_iso(),
            )
        )

    try:
        for route_path in routes:
            elapsed = clock() - started_at
            if elapsed > effective_budget.active_deadline_seconds:
                raise CrawlDeadlineExceededError(
                    f"discovery run exceeded its {effective_budget.active_deadline_seconds}s "
                    "deadline",
                    context={
                        "elapsed_seconds": elapsed,
                        "active_deadline_seconds": effective_budget.active_deadline_seconds,
                        "routes_completed": len(records),
                        "routes_requested": len(routes),
                    },
                )

            decision = crawler.check_robots(route_path)
            if not decision.allowed:
                records.append(
                    ContentRecordProjection(
                        route_path=route_path,
                        render_mode=RenderMode.UNKNOWN,
                        robots_allowed=False,
                        canonical_url=None,
                        sitemap_listed=False,
                        structured_data_present=False,
                        evidence_ref="",
                        observed_at=_utc_now_iso(),
                    )
                )
                _audit(
                    route_path,
                    "skipped_robots_disallowed",
                    JobError(
                        error_code="saena.policy_denied.robots_disallowed",
                        summary=f"route {route_path} disallowed by robots policy",
                        retryable=False,
                    ),
                )
                continue

            record = _fetch_with_retries(
                crawler, route_path, max_retries=effective_budget.max_retries
            )
            records.append(record)
            _audit(route_path, "fetched", None)
    except (CrawlDeadlineExceededError, CrawlRetryExhaustedError):
        transition(status, JobStatus.FAILED)
        raise

    status = transition(status, JobStatus.SUCCEEDED).status

    observation = SiteInventoryObservation(
        job_context=job_context,
        site_id=site_id,
        inventory_version=inventory_version,
        records=tuple(records),
        audit_trail=tuple(audit_trail),
        captured_at=_utc_now_iso(),
    )
    payload = build_site_inventory_completed_payload(
        site_id=site_id, inventory_version=inventory_version
    )
    return SiteDiscoveryRunResult(
        observation=observation, event_payload=payload, final_status=status
    )


__all__ = [
    "AuditEntry",
    "SiteDiscoveryRunResult",
    "SiteInventoryObservation",
    "run_site_discovery",
]
