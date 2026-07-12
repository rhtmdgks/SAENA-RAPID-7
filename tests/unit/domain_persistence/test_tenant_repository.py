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
    """`update_status` returns the new status string directly (critic
    MUST-FIX 4) — it constructs no `TenantContext` wrapper, so it never
    raises the identity-layer status gate."""
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    repo.put(tenant_id, make_tenant_context(status="active"))

    updated = repo.update_status(tenant_id, "active")

    assert updated == "active"
    assert repo.get(tenant_id).status == "active"


def test_update_status_to_suspended_succeeds_and_get_then_raises() -> None:
    """`update_status` to a non-active status succeeds (gate-free, critic
    MUST-FIX 4) — the gated `get()` accessor is what raises for a
    suspended/terminating stored record, exactly as `saena_domain.identity`
    intends: `TenantContext`'s own construction-time status gate fires on
    `get()`, never on the write itself."""
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    repo.put(tenant_id, make_tenant_context(status="active"))

    updated = repo.update_status(tenant_id, "suspended")

    assert updated == "suspended"
    with pytest.raises(TenantSuspendedError):
        repo.get(tenant_id)


def test_suspend_view_via_get_record_then_reactivate_round_trip() -> None:
    """Coordinator MUST-FIX 4 scenario: suspend -> get_record shows
    suspended -> update_status back to active -> get() works again. Models
    w2-08 tenant-control's admin suspend -> view -> reactivate flow without
    ever weakening `saena_domain.identity`'s construction-time status gate."""
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    repo.put(tenant_id, make_tenant_context(status="active"))

    repo.update_status(tenant_id, "suspended")
    record = repo.get_record(tenant_id)
    assert record.status == "suspended"
    assert record.tenant_id == "acme-co"
    assert record.raw_payload["status"] == "suspended"

    repo.update_status(tenant_id, "active")
    ctx = repo.get(tenant_id)
    assert ctx.status == "active"


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


def test_get_record_missing_tenant_raises_not_found() -> None:
    repo = InMemoryTenantRepository()

    with pytest.raises(NotFoundError):
        repo.get_record(TenantId("acme-co"))


def test_get_record_never_raises_for_active_tenant() -> None:
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    repo.put(tenant_id, make_tenant_context(status="active"))

    record = repo.get_record(tenant_id)

    assert record.status == "active"
    assert record.tenant_id == "acme-co"


def test_get_record_raw_payload_is_immutable_and_does_not_leak_mutation() -> None:
    """`raw_payload` is a `MappingProxyType` over a deep-copied dict —
    mutating the caller's own reference to it must be impossible (assignment
    raises `TypeError`) and mutating the underlying dict independently must
    never affect a second `get_record` call's own copy."""
    repo = InMemoryTenantRepository()
    tenant_id = TenantId("acme-co")
    repo.put(tenant_id, make_tenant_context(status="active"))

    record = repo.get_record(tenant_id)
    with pytest.raises(TypeError):
        record.raw_payload["status"] = "tampered"  # type: ignore[index]

    second = repo.get_record(tenant_id)
    assert second.raw_payload["status"] == "active"
