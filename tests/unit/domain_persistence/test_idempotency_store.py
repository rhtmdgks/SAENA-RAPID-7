"""Tests for `InMemoryIdempotencyStore` (`IdempotencyStore` port)."""

from __future__ import annotations

from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryIdempotencyStore

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def test_unseen_key_returns_false() -> None:
    store = InMemoryIdempotencyStore()

    assert store.seen(TENANT_A, "acme-co:run-1:patch-unit-1") is False


def test_mark_then_seen_returns_true() -> None:
    store = InMemoryIdempotencyStore()
    key = "acme-co:run-1:patch-unit-1"

    store.mark(TENANT_A, key)

    assert store.seen(TENANT_A, key) is True


def test_mark_is_idempotent() -> None:
    store = InMemoryIdempotencyStore()
    key = "acme-co:run-1:patch-unit-1"

    store.mark(TENANT_A, key)
    store.mark(TENANT_A, key)  # no error, no duplicate-state effect

    assert store.seen(TENANT_A, key) is True


def test_keys_are_isolated_per_tenant() -> None:
    store = InMemoryIdempotencyStore()
    key = "shared-key-shape:run-1:patch-unit-1"

    store.mark(TENANT_A, key)

    assert store.seen(TENANT_A, key) is True
    assert store.seen(TENANT_B, key) is False
