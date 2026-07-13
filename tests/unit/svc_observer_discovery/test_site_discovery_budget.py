"""Rate/timeout/retry enforcement for `run_site_discovery`, and its
`JobKind.SITE_DISCOVERY`-scope guard."""

from __future__ import annotations

import pytest
from observer_discovery_factories import build_job_context
from saena_domain.execution import JobKind, resource_limits_for
from saena_site_discovery import (
    CrawlBudget,
    CrawlBudgetExceededError,
    CrawlDeadlineExceededError,
    CrawlRetryExhaustedError,
    FakeSiteCrawler,
    FetchedRoute,
    JobKindScopeError,
    RenderMode,
    crawl_budget_for,
    run_site_discovery,
)


def test_crawl_budget_for_derives_from_resource_limits_for() -> None:
    limits = resource_limits_for(JobKind.SITE_DISCOVERY)
    budget = crawl_budget_for(JobKind.SITE_DISCOVERY)

    assert budget.max_retries == limits.max_retries
    assert budget.active_deadline_seconds == limits.active_deadline_seconds
    assert budget.max_routes_per_run > 0
    assert budget.request_timeout_seconds > 0


@pytest.mark.parametrize("other_kind", [JobKind.CHATGPT_OBSERVER, JobKind.AGENT_RUNNER])
def test_crawl_budget_for_rejects_any_other_job_kind(other_kind: JobKind) -> None:
    with pytest.raises(JobKindScopeError):
        crawl_budget_for(other_kind)


def _fetched_route() -> FetchedRoute:
    return FetchedRoute(
        render_mode=RenderMode.STATIC,
        canonical_url=None,
        sitemap_listed=False,
        structured_data_present=False,
        evidence_ref="evidence://acme-co/page",
    )


def test_too_many_routes_raises_budget_exceeded_before_any_fetch() -> None:
    crawler = FakeSiteCrawler()
    tiny_budget = CrawlBudget(
        max_routes_per_run=1,
        request_timeout_seconds=1.0,
        max_retries=1,
        active_deadline_seconds=3600,
    )

    with pytest.raises(CrawlBudgetExceededError):
        run_site_discovery(
            job_context=build_job_context(),
            crawler=crawler,
            site_id="site-0001",
            inventory_version="v1",
            routes=["/", "/pricing"],
            budget=tiny_budget,
        )

    assert crawler.robots_calls == []
    assert crawler.fetch_calls == []


def test_deadline_exceeded_mid_run_raises_and_stops() -> None:
    crawler = FakeSiteCrawler()
    crawler.register_route("/", _fetched_route())
    crawler.register_route("/pricing", _fetched_route())
    budget = CrawlBudget(
        max_routes_per_run=10,
        request_timeout_seconds=1.0,
        max_retries=1,
        active_deadline_seconds=5,
    )
    # Fake clock: first call (elapsed baseline) returns 0, every subsequent
    # call jumps far past the 5s deadline.
    calls = {"count": 0}

    def fake_clock() -> float:
        calls["count"] += 1
        return 0.0 if calls["count"] == 1 else 999.0

    with pytest.raises(CrawlDeadlineExceededError):
        run_site_discovery(
            job_context=build_job_context(),
            crawler=crawler,
            site_id="site-0001",
            inventory_version="v1",
            routes=["/", "/pricing"],
            budget=budget,
            clock=fake_clock,
        )

    # The deadline check happens BEFORE the first route is even touched
    # (elapsed is checked at the top of every loop iteration) — no route
    # was fetched or even robots-checked once the deadline had passed.
    assert crawler.fetch_calls == []
    assert crawler.robots_calls == []


def test_retry_succeeds_within_max_retries() -> None:
    crawler = FakeSiteCrawler()
    crawler.register_route("/", _fetched_route())
    crawler.fail_next("/", times=2)
    budget = CrawlBudget(
        max_routes_per_run=10,
        request_timeout_seconds=1.0,
        max_retries=3,
        active_deadline_seconds=3600,
    )

    result = run_site_discovery(
        job_context=build_job_context(),
        crawler=crawler,
        site_id="site-0001",
        inventory_version="v1",
        routes=["/"],
        budget=budget,
    )

    assert len(result.observation.records) == 1
    assert result.observation.records[0].robots_allowed is True
    # 2 failures + 1 success = 3 fetch_route calls.
    assert crawler.fetch_calls == ["/", "/", "/"]


def test_retry_exhausted_raises() -> None:
    crawler = FakeSiteCrawler()
    crawler.register_route("/", _fetched_route())
    crawler.fail_next("/", times=5)
    budget = CrawlBudget(
        max_routes_per_run=10,
        request_timeout_seconds=1.0,
        max_retries=2,
        active_deadline_seconds=3600,
    )

    with pytest.raises(CrawlRetryExhaustedError):
        run_site_discovery(
            job_context=build_job_context(),
            crawler=crawler,
            site_id="site-0001",
            inventory_version="v1",
            routes=["/"],
            budget=budget,
        )
