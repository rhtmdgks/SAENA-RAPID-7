"""`saena_policy_gate.errors` — taxonomy shape (ADR-0015)."""

from __future__ import annotations

import re

from saena_policy_gate.errors import (
    DecisionConflictError,
    GateUnavailableError,
    PolicyDenyError,
    PolicyGateError,
    TenantHeaderError,
    ValidationError,
)

_ERROR_CODE_PATTERN = re.compile(r"^saena\.[a-z_]+\.[a-z_]+$")


def test_gate_unavailable_is_policy_deny_subclass() -> None:
    assert issubclass(GateUnavailableError, PolicyDenyError)
    assert issubclass(PolicyDenyError, PolicyGateError)


def test_gate_unavailable_error_code_and_retryable() -> None:
    exc = GateUnavailableError("engine down")
    assert exc.error_code == "saena.policy_denied.gate_unavailable"
    assert exc.retryable is False


def test_to_dict_carries_error_code_and_context() -> None:
    exc = ValidationError("bad shape", context={"field": "kind"})
    payload = exc.to_dict()
    assert payload["error_code"] == "saena.validation.schema_mismatch"
    assert payload["field"] == "kind"
    assert payload["message"] == "bad shape"


def test_context_defaults_to_empty_dict() -> None:
    exc = ValidationError("bad")
    assert exc.context == {}


def test_every_error_code_matches_adr_0015_pattern() -> None:
    for cls in (
        PolicyGateError,
        PolicyDenyError,
        GateUnavailableError,
        ValidationError,
        DecisionConflictError,
        TenantHeaderError,
    ):
        assert _ERROR_CODE_PATTERN.fullmatch(cls.error_code), cls.error_code
