"""`SiteCrawlerPort` — read-only crawl adapter Protocol + in-memory fake.

Structurally READ-ONLY: `SiteCrawlerPort` declares exactly two methods
(`check_robots`, `fetch_route`), both pure reads against whatever transport
a real implementation uses (an actual crawl/browser-pool client — W4, out
of this unit's scope, see module docstring in `inventory.py`). There is NO
write/mutate/save/delete method on this Protocol AT ALL — deliverable 5
("assert NO write/mutation capability exists") is a structural fact about
this class's shape, not a runtime permission check; see
`tests/unit/svc_observer_discovery/test_read_only_protocols.py` for the
assertion that enumerates this Protocol's members and confirms it.

`FakeSiteCrawler` is a deterministic, in-memory reference implementation —
NO real network or browser I/O happens anywhere in this package or its
tests (mission constraint).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from saena_site_discovery.errors import SiteDiscoveryError
from saena_site_discovery.records import RenderMode


class UnknownRouteError(SiteDiscoveryError):
    """`FakeSiteCrawler` was asked about a route it has no canned response
    for — a test-harness misconfiguration, not a production concern."""

    error_code = "saena.not_found.crawler_fixture_route"


class TransientFetchError(SiteDiscoveryError):
    """A route's fetch failed in a way `inventory.run_site_discovery`
    treats as retryable up to `CrawlBudget.max_retries` (simulates a
    real crawler's transient network/timeout failure)."""

    error_code = "saena.upstream_engine.transient_fetch_failure"
    retryable = True


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    """Result of a robots-policy check for one route — READ-only fact,
    never itself performs (or implies) a fetch."""

    allowed: bool


@dataclass(frozen=True, slots=True)
class FetchedRoute:
    """Result of actually fetching one route (only called when
    `RobotsDecision.allowed` is `True` — see `inventory.py`)."""

    render_mode: RenderMode
    canonical_url: str | None
    sitemap_listed: bool
    structured_data_present: bool
    evidence_ref: str


@runtime_checkable
class SiteCrawlerPort(Protocol):
    """READ-ONLY crawl adapter Protocol.

    Exactly two methods exist on this Protocol, both reads — there is
    structurally no write/mutate verb here (contrast
    `saena_artifact_registry.blobstore.BlobStore`, which legitimately needs
    a `put_blob` because artifact-registry OWNS blob writes; this service's
    ADR-0004 profile is "read-only 크롤, Git credential 미발급" — it must
    never be ABLE to write to the site/repo it inventories, and this
    Protocol's shape enforces that at the type level, not just by
    convention).
    """

    def check_robots(self, route_path: str) -> RobotsDecision:
        """Return whether `route_path` may be fetched at all, per the
        target site's robots policy. MUST be called, and MUST return
        `allowed=False`, before any fetch is attempted for a disallowed
        route — `fetch_route` must never be called in that case (the
        robots/policy boundary hook `inventory.run_site_discovery`
        enforces this at the call-site level)."""
        ...

    def fetch_route(self, route_path: str) -> FetchedRoute:
        """Fetch `route_path` and return its discovery-relevant facts.
        Raises `TransientFetchError` for a simulated transient failure
        (retryable up to `CrawlBudget.max_retries`)."""
        ...


@dataclass
class FakeSiteCrawler:
    """Deterministic in-memory `SiteCrawlerPort` — the ONLY crawler
    implementation this patch unit ships (no real network/browser I/O,
    mission constraint). Configure canned `RobotsDecision`/`FetchedRoute`
    responses per route via `register_route`/`register_disallowed`, and
    optionally schedule N transient failures before success via
    `fail_next`. Records every call it receives (`robots_calls`/
    `fetch_calls`) so tests can assert `fetch_route` was never called for a
    robots-disallowed route.
    """

    _robots: dict[str, RobotsDecision] = field(default_factory=dict)
    _fetched: dict[str, FetchedRoute] = field(default_factory=dict)
    _remaining_failures: dict[str, int] = field(default_factory=dict)
    robots_calls: list[str] = field(default_factory=list)
    fetch_calls: list[str] = field(default_factory=list)

    def register_route(self, route_path: str, fetched: FetchedRoute) -> None:
        """Register `route_path` as robots-ALLOWED with the given canned
        `FetchedRoute` result."""
        self._robots[route_path] = RobotsDecision(allowed=True)
        self._fetched[route_path] = fetched

    def register_disallowed(self, route_path: str) -> None:
        """Register `route_path` as robots-DISALLOWED — `fetch_route` must
        never be called for it (asserted via `fetch_calls`)."""
        self._robots[route_path] = RobotsDecision(allowed=False)

    def fail_next(self, route_path: str, *, times: int) -> None:
        """Make the next `times` `fetch_route(route_path)` calls raise
        `TransientFetchError` before finally returning the registered
        `FetchedRoute` (route must already be `register_route`d)."""
        self._remaining_failures[route_path] = times

    def check_robots(self, route_path: str) -> RobotsDecision:
        self.robots_calls.append(route_path)
        decision = self._robots.get(route_path)
        if decision is None:
            raise UnknownRouteError(
                f"no fixture registered for route {route_path!r}",
                context={"route_path": route_path},
            )
        return decision

    def fetch_route(self, route_path: str) -> FetchedRoute:
        self.fetch_calls.append(route_path)
        remaining = self._remaining_failures.get(route_path, 0)
        if remaining > 0:
            self._remaining_failures[route_path] = remaining - 1
            raise TransientFetchError(
                f"simulated transient fetch failure for {route_path!r}",
                context={"route_path": route_path},
            )
        fetched = self._fetched.get(route_path)
        if fetched is None:
            raise UnknownRouteError(
                f"no fixture registered for route {route_path!r}",
                context={"route_path": route_path},
            )
        return fetched


__all__ = [
    "FakeSiteCrawler",
    "FetchedRoute",
    "RobotsDecision",
    "SiteCrawlerPort",
    "TransientFetchError",
    "UnknownRouteError",
]
