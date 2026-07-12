"""Tests for `saena_domain.persistence.errors` — shared exception shape."""

from __future__ import annotations

from saena_domain.persistence.errors import PersistenceError, TenantIsolationError


def test_to_dict_includes_error_code_message_and_context() -> None:
    err = TenantIsolationError("cross-tenant access denied", context={"tenant_id": "acme-co"})

    result = err.to_dict()

    assert result == {
        "error_code": "saena.persistence.tenant_isolation_violation",
        "message": "cross-tenant access denied",
        "tenant_id": "acme-co",
    }


def test_base_error_defaults_to_empty_context() -> None:
    err = PersistenceError("generic failure")

    assert err.context == {}
    assert err.to_dict() == {
        "error_code": "saena.persistence.error",
        "message": "generic failure",
    }
