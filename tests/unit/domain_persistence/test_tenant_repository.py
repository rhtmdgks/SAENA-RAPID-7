"""Tests for `InMemoryTenantRepository` (`TenantRepository` port)."""

from __future__ import annotations

import pytest
from persistence_factories import make_tenant_context
from saena_domain.identity import TenantId
from saena_domain.identity.errors import TenantSuspendedError
from saena_domain.persistence import InMemoryTenantRepository, NotFoundError


def test_put_then_get_round_trips() -> None:
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    ctx = make_tenant_context()

    repo.put(tenant_id, ctx)

    assert repo.get(tenant_id) == ctx


def test_get_missing_tenant_raises_not_found() -> None:
    repo = InMemoryTenantRepository()

    with pytest.raises(NotFoundError):
        repo.get(TenantId("acme-co"))


def test_put_rejects_mismatched_tenant_id() -> None:
    repo = InMemoryTenantRepository()
    ctx = make_tenant_context()  # tenant_id == "acme-co"

    with pytest.raises(ValueError, match="does not match"):
        repo.put(TenantId("globex-co"), ctx)


def test_put_is_idempotent_upsert() -> None:
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    ctx = make_tenant_context()

    repo.put(tenant_id, ctx)
    repo.put(tenant_id, ctx)  # replay — no error

    assert repo.get(tenant_id) == ctx


def test_update_status_replaces_stored_status() -> None:
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    repo.put(tenant_id, make_tenant_context(status="active"))

    updated = repo.update_status(tenant_id, "active")

    assert updated.status == "active"
    assert repo.get(tenant_id).status == "active"


def test_update_status_to_suspended_persists_but_raises_on_reconstruction() -> None:
    """`TenantContext`'s own construction-time status gate
    (`saena_domain.identity.tenant`) fires on every read — a suspended
    tenant's context is never handed back as a usable object, by identity
    layer design. The write itself still lands: a subsequent `get()` raises
    the SAME error (not `NotFoundError`), proving the status was persisted,
    not silently dropped."""
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    repo.put(tenant_id, make_tenant_context(status="active"))

    with pytest.raises(TenantSuspendedError):
        repo.update_status(tenant_id, "suspended")

    with pytest.raises(TenantSuspendedError):
        repo.get(tenant_id)


def test_update_status_missing_tenant_raises_not_found() -> None:
    repo = InMemoryTenantRepository()

    with pytest.raises(NotFoundError):
        repo.update_status(TenantId("acme-co"), "suspended")


def test_cross_tenant_get_is_isolated_not_leaked() -> None:
    """Tenant A's repo has no record for tenant B — accessing tenant B's
    key returns NotFoundError, never tenant A's data."""
    repo = InMemoryTenantRepository()
    tenant_a = TenantId("acme-co")
    tenant_b = TenantId("globex-co")
    repo.put(tenant_a, make_tenant_context(tenant_id="acme-co", namespace="saena-tenant-acme-co"))

    with pytest.raises(NotFoundError):
        repo.get(tenant_b)
