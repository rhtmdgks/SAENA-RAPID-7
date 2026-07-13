"""saena_site_discovery — site-discovery-service (W3, `JobKind.SITE_DISCOVERY`).

Read-only, tenant-scoped site/route inventory pass: robots-boundary-checked
crawl over a `SiteCrawlerPort` adapter (fake-only in this patch unit — real
crawler/browser-pool client is W4), producing an immutable
`SiteInventoryObservation` (with per-route `ContentRecordProjection`s and an
audit trail) and the `site.inventory.completed.v1` event payload built for
it. See `services/acquisition/site-discovery-service/README.md` and
`docs/architecture/execution-runtime.md` for the bounded-context write-up.

W3 MINIMAL scope — explicitly OUT of this package (Wave 4 or later,
deliberately not implemented here): a real Playwright/browser-pool crawler
client, demand-graph/intervention-generator consumption logic, any
scoring/recommendation over captured records, ClickHouse/vector storage.

Public API:
    ContentRecordProjection / RenderMode
    SiteCrawlerPort / FakeSiteCrawler / RobotsDecision / FetchedRoute /
        TransientFetchError / UnknownRouteError
    CrawlBudget / crawl_budget_for
    AuditEntry / SiteInventoryObservation / SiteDiscoveryRunResult /
        run_site_discovery
    InMemorySiteInventoryStore
    SiteDiscoveryError and every specific error subclass
"""

from __future__ import annotations

from saena_site_discovery.budget import CrawlBudget, crawl_budget_for
from saena_site_discovery.crawler import (
    FakeSiteCrawler,
    FetchedRoute,
    RobotsDecision,
    SiteCrawlerPort,
    TransientFetchError,
    UnknownRouteError,
)
from saena_site_discovery.errors import (
    CrawlBudgetExceededError,
    CrawlDeadlineExceededError,
    CrawlRetryExhaustedError,
    CrossTenantObservationError,
    JobKindScopeError,
    SiteDiscoveryError,
    SiteInventoryNotFoundError,
)
from saena_site_discovery.inventory import (
    AuditEntry,
    SiteDiscoveryRunResult,
    SiteInventoryObservation,
    run_site_discovery,
)
from saena_site_discovery.records import ContentRecordProjection, RecordValidationError, RenderMode
from saena_site_discovery.store import InMemorySiteInventoryStore

__all__ = [
    "AuditEntry",
    "ContentRecordProjection",
    "CrawlBudget",
    "CrawlBudgetExceededError",
    "CrawlDeadlineExceededError",
    "CrawlRetryExhaustedError",
    "CrossTenantObservationError",
    "FakeSiteCrawler",
    "FetchedRoute",
    "InMemorySiteInventoryStore",
    "JobKindScopeError",
    "RecordValidationError",
    "RenderMode",
    "RobotsDecision",
    "SiteCrawlerPort",
    "SiteDiscoveryError",
    "SiteDiscoveryRunResult",
    "SiteInventoryNotFoundError",
    "SiteInventoryObservation",
    "TransientFetchError",
    "UnknownRouteError",
    "crawl_budget_for",
    "run_site_discovery",
]
