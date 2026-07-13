"""Cross-tenant `SiteInventoryObservation` storage/read rejected."""

from __future__ import annotations

import pytest
from observer_discovery_factories import TENANT_A, TENANT_B, build_job_context
from saena_site_discovery import (
    CrossTenantObservationError,
    FakeSiteCrawler,
    InMemorySiteInventoryStore,
    SiteInventoryNotFoundError,
    run_site_discovery,
)


def _observation_for(tenant_id: str):
    crawler = FakeSiteCrawler()
    result = run_site_discovery(
        job_context=build_job_context(tenant_id=tenant_id),
        crawler=crawler,
        site_id="site-0001",
        inventory_version="v1",
        routes=[],
    )
    return result.observation


def test_put_rejects_observation_captured_under_a_different_tenant() -> None:
    store = InMemorySiteInventoryStore()
    observation = _observation_for(TENANT_A)

    with pytest.raises(CrossTenantObservationError):
        store.put(TENANT_B, "site-0001", observation)


def test_get_never_leaks_a_different_tenants_observation() -> None:
    store = InMemorySiteInventoryStore()
    observation = _observation_for(TENANT_A)
    store.put(TENANT_A, "site-0001", observation)

    with pytest.raises(SiteInventoryNotFoundError):
        store.get(TENANT_B, "site-0001")


def test_get_round_trips_for_the_owning_tenant() -> None:
    store = InMemorySiteInventoryStore()
    observation = _observation_for(TENANT_A)
    store.put(TENANT_A, "site-0001", observation)

    assert store.get(TENANT_A, "site-0001") == observation
