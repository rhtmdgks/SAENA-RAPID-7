"""`errors.py` — error_code stability + structured `.context`/`.to_dict()`."""

from __future__ import annotations

from saena_claim_evidence import (
    ClaimEvidenceError,
    ClaimNotFoundError,
    CrossTenantLedgerAccessError,
    DuplicateClaimIdError,
    DuplicateEvidenceIdError,
    EvidenceClaimMismatchError,
    LedgerIntegrityError,
    UnknownEvidenceLinkError,
)


def test_base_error_carries_message_and_context() -> None:
    err = ClaimEvidenceError("boom", context={"foo": "bar"})
    assert str(err) == "boom"
    assert err.context == {"foo": "bar"}
    assert err.to_dict() == {"error_code": err.error_code, "message": "boom", "foo": "bar"}


def test_base_error_defaults_to_empty_context() -> None:
    err = ClaimEvidenceError("boom")
    assert err.context == {}


def test_every_specific_error_has_a_stable_saena_namespaced_error_code() -> None:
    specific_errors = [
        DuplicateClaimIdError("x"),
        DuplicateEvidenceIdError("x"),
        ClaimNotFoundError("x"),
        EvidenceClaimMismatchError("x"),
        UnknownEvidenceLinkError("x"),
        CrossTenantLedgerAccessError("x"),
        LedgerIntegrityError("x"),
    ]
    seen_codes: set[str] = set()
    for err in specific_errors:
        assert err.error_code.startswith("saena.")
        assert err.error_code not in seen_codes, f"duplicate error_code: {err.error_code}"
        seen_codes.add(err.error_code)
        assert isinstance(err, ClaimEvidenceError)


def test_error_to_dict_never_includes_claim_text_or_excerpt_keys_by_default() -> None:
    """Redaction discipline (errors.py docstring): context must never carry
    raw claim_text/excerpt content — this pins the DEFAULT construction
    path never smuggles such a key in on its own."""
    err = ClaimNotFoundError("claim not found", context={"claim_id": "claim-0001"})
    assert "claim_text" not in err.to_dict()
    assert "excerpt" not in err.to_dict()
