"""Tests for `saena_experiment_attribution.boundary.errors`.

Covers the uniform non-leaking error surface (deliverable #4): one shape
(`BoundaryLookupAbsent`) for every cross-tenant/not-found outcome, and the
structured `.to_dict()` representation every boundary error carries.
"""

from __future__ import annotations

from saena_experiment_attribution.boundary.errors import (
    BasisDerivationError,
    BoundaryError,
    BoundaryLookupAbsent,
    EngineNotPermittedError,
    PayloadValidationError,
    PublishRefusedError,
    TenantDuplicationError,
)


def test_to_dict_structured_log_safe_representation():
    error = BoundaryError("something went wrong", context={"field": "x"})

    dumped = error.to_dict()

    assert dumped == {
        "error_code": "saena.experiment_attribution.boundary.error",
        "message": "something went wrong",
        "field": "x",
    }


def test_to_dict_without_context_has_no_extra_keys():
    error = BoundaryError("plain message")

    dumped = error.to_dict()

    assert dumped == {
        "error_code": "saena.experiment_attribution.boundary.error",
        "message": "plain message",
    }


def test_boundary_lookup_absent_is_the_uniform_shape_for_every_miss():
    """A cross-tenant guess and a genuinely-nonexistent record raise the
    SAME exception type/shape -- no distinguishing field."""
    wrong_tenant = BoundaryLookupAbsent(
        "no record for this key", context={"lookup_key": "compound-key-1"}
    )
    never_existed = BoundaryLookupAbsent(
        "no record for this key", context={"lookup_key": "compound-key-2"}
    )

    assert type(wrong_tenant) is type(never_existed)
    assert wrong_tenant.error_code == never_existed.error_code
    assert set(wrong_tenant.to_dict().keys()) == set(never_existed.to_dict().keys())


def test_error_codes_are_distinct_per_category():
    codes = {
        BoundaryError.error_code,
        BoundaryLookupAbsent.error_code,
        PayloadValidationError.error_code,
        TenantDuplicationError.error_code,
        EngineNotPermittedError.error_code,
        PublishRefusedError.error_code,
        BasisDerivationError.error_code,
    }

    assert len(codes) == 7


def test_tenant_duplication_error_is_a_payload_validation_error():
    error = TenantDuplicationError("dup", context={"field": "tenant_id"})

    assert isinstance(error, PayloadValidationError)
    assert isinstance(error, BoundaryError)


def test_context_is_copied_not_aliased():
    original_context = {"field": "x"}
    error = BoundaryError("msg", context=original_context)
    original_context["field"] = "mutated"

    assert error.context["field"] == "x"
