"""Robots/policy boundary hook: a disallow must skip + record, never fetch."""

from __future__ import annotations

from observer_discovery_factories import build_job_context
from saena_site_discovery import FakeSiteCrawler, FetchedRoute, RenderMode, run_site_discovery


def test_robots_disallowed_route_is_never_fetched() -> None:
    crawler = FakeSiteCrawler()
    crawler.register_disallowed("/admin")
    crawler.register_route(
        "/",
        FetchedRoute(
            render_mode=RenderMode.SERVER_SIDE,
            canonical_url="https://example.com/",
            sitemap_listed=True,
            structured_data_present=True,
            evidence_ref="evidence://acme-co/root-page",
        ),
    )

    result = run_site_discovery(
        job_context=build_job_context(),
        crawler=crawler,
        site_id="site-0001",
        inventory_version="v1",
        routes=["/admin", "/"],
    )

    # The negative fact this test exists to prove: fetch_route was NEVER
    # called for the disallowed route.
    assert "/admin" not in crawler.fetch_calls
    assert crawler.fetch_calls == ["/"]

    admin_record = next(r for r in result.observation.records if r.route_path == "/admin")
    assert admin_record.robots_allowed is False
    assert admin_record.evidence_ref == ""
    assert admin_record.canonical_url is None

    root_record = next(r for r in result.observation.records if r.route_path == "/")
    assert root_record.robots_allowed is True
    assert root_record.evidence_ref


def test_robots_disallowed_route_is_audited_with_policy_denied_error() -> None:
    crawler = FakeSiteCrawler()
    crawler.register_disallowed("/admin")

    result = run_site_discovery(
        job_context=build_job_context(),
        crawler=crawler,
        site_id="site-0001",
        inventory_version="v1",
        routes=["/admin"],
    )

    entry = result.observation.audit_trail[0]
    assert entry.action == "skipped_robots_disallowed"
    assert entry.detail is not None
    assert entry.detail.error_code == "saena.policy_denied.robots_disallowed"
    assert entry.detail.retryable is False
