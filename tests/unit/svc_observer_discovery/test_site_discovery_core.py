"""Happy-path `run_site_discovery`: fetch, project, audit, emit."""

from __future__ import annotations

import dataclasses

import pytest
from observer_discovery_factories import build_job_context
from saena_domain.execution import JobStatus
from saena_site_discovery import (
    FakeSiteCrawler,
    FetchedRoute,
    RenderMode,
    run_site_discovery,
)


def _crawler_with_two_allowed_routes() -> FakeSiteCrawler:
    crawler = FakeSiteCrawler()
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
    crawler.register_route(
        "/pricing",
        FetchedRoute(
            render_mode=RenderMode.STATIC,
            canonical_url="https://example.com/pricing",
            sitemap_listed=True,
            structured_data_present=False,
            evidence_ref="evidence://acme-co/pricing-page",
        ),
    )
    return crawler


def test_run_site_discovery_happy_path_produces_records_and_audit() -> None:
    job_context = build_job_context()
    crawler = _crawler_with_two_allowed_routes()

    result = run_site_discovery(
        job_context=job_context,
        crawler=crawler,
        site_id="site-0001",
        inventory_version="v1",
        routes=["/", "/pricing"],
    )

    assert result.final_status == JobStatus.SUCCEEDED
    assert len(result.observation.records) == 2
    assert {record.route_path for record in result.observation.records} == {"/", "/pricing"}
    assert all(record.robots_allowed for record in result.observation.records)
    assert all(record.evidence_ref for record in result.observation.records)
    assert len(result.observation.audit_trail) == 2
    assert all(entry.action == "fetched" for entry in result.observation.audit_trail)
    assert all(entry.tenant_id == job_context.tenant_id for entry in result.observation.audit_trail)
    assert crawler.fetch_calls == ["/", "/pricing"]


def test_run_site_discovery_event_payload_matches_contract_fields() -> None:
    job_context = build_job_context()
    crawler = _crawler_with_two_allowed_routes()

    result = run_site_discovery(
        job_context=job_context,
        crawler=crawler,
        site_id="site-0001",
        inventory_version="v2",
        routes=["/"],
    )

    assert result.event_payload == {"site_id": "site-0001", "inventory_version": "v2"}


def test_site_inventory_observation_is_frozen_immutable() -> None:
    job_context = build_job_context()
    crawler = _crawler_with_two_allowed_routes()
    result = run_site_discovery(
        job_context=job_context,
        crawler=crawler,
        site_id="site-0001",
        inventory_version="v1",
        routes=["/"],
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.observation.site_id = "tampered"  # type: ignore[misc]

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.observation.records[0].route_path = "tampered"  # type: ignore[misc]
