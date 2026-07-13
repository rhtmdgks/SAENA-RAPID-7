"""Unit tests for `saena_domain.qeeg.errors`."""

from __future__ import annotations

from saena_domain.qeeg.errors import (
    CrossTenantProjectionAccessError,
    QeegProjectionError,
    UnknownClaimError,
    UnknownEntityError,
)


def test_base_error_default_code_and_empty_context() -> None:
    err = QeegProjectionError("boom")
    assert err.error_code == "saena.internal.qeeg_projection_error"
    assert err.context == {}
    assert str(err) == "boom"


def test_base_error_to_dict() -> None:
    err = QeegProjectionError("boom", context={"claim_id": "c1"})
    assert err.to_dict() == {
        "error_code": "saena.internal.qeeg_projection_error",
        "message": "boom",
        "claim_id": "c1",
    }


def test_cross_tenant_error_code() -> None:
    err = CrossTenantProjectionAccessError("denied")
    assert err.error_code == "saena.auth.cross_tenant_denied"
    assert isinstance(err, QeegProjectionError)


def test_unknown_claim_error_code() -> None:
    err = UnknownClaimError("nope")
    assert err.error_code == "saena.not_found.qeeg_claim"


def test_unknown_entity_error_code() -> None:
    err = UnknownEntityError("nope")
    assert err.error_code == "saena.not_found.qeeg_entity"


def test_context_is_copied_not_aliased() -> None:
    ctx = {"claim_id": "c1"}
    err = QeegProjectionError("boom", context=ctx)
    ctx["claim_id"] = "mutated"
    assert err.context["claim_id"] == "c1"
