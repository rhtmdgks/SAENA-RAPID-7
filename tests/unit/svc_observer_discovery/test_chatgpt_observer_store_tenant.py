"""Cross-tenant `PlatformObservation` storage/read rejected."""

from __future__ import annotations

import pytest
from observer_discovery_factories import CHATGPT_SEARCH_ENGINE_ID, TENANT_A, TENANT_B
from saena_chatgpt_observer import (
    CrossTenantObservationError,
    InMemoryObservationStore,
    ObservationNotFoundError,
    PlatformObservation,
)


def _observation_for(tenant_id: str) -> PlatformObservation:
    return PlatformObservation(
        engine_id=CHATGPT_SEARCH_ENGINE_ID,
        tenant_id=tenant_id,
        run_id="run-0001",
        query_text="q",
        citation_refs=(),
        raw_object_ref="raw://acme-co/x",
        observed_at="2026-07-13T00:00:00Z",
    )


def test_put_rejects_observation_captured_under_a_different_tenant() -> None:
    store = InMemoryObservationStore()
    observation = _observation_for(TENANT_A)

    with pytest.raises(CrossTenantObservationError):
        store.put(TENANT_B, observation)


def test_get_never_leaks_a_different_tenants_observation() -> None:
    store = InMemoryObservationStore()
    observation = _observation_for(TENANT_A)
    store.put(TENANT_A, observation)

    with pytest.raises(ObservationNotFoundError):
        store.get(TENANT_B, "run-0001", "q")


def test_get_round_trips_for_the_owning_tenant() -> None:
    store = InMemoryObservationStore()
    observation = _observation_for(TENANT_A)
    store.put(TENANT_A, observation)

    assert store.get(TENANT_A, "run-0001", "q") == observation
