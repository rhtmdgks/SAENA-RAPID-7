"""`saena_policy_gate.problem` — RFC 9457 problem+json shape (ADR-0015)."""

from __future__ import annotations

import re

from saena_policy_gate.errors import GateUnavailableError, ValidationError
from saena_policy_gate.problem import build_problem, new_trace_id

_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def test_new_trace_id_is_32_hex_lowercase() -> None:
    trace_id = new_trace_id()
    assert _TRACE_ID_PATTERN.fullmatch(trace_id)


def test_build_problem_required_fields() -> None:
    exc = ValidationError("bad request shape", context={"field": "kind"})
    problem = build_problem(exc, instance="https://gate.local/v1/gate/authorize")
    assert problem["type"] == "https://schemas.the-saena.ai/errors/validation/schema_mismatch"
    assert problem["title"] == "ValidationError"
    assert problem["status"] == 400
    assert problem["detail"] == "bad request shape"
    assert problem["instance"] == "https://gate.local/v1/gate/authorize"
    assert problem["error_code"] == "saena.validation.schema_mismatch"
    assert problem["retryable"] is False
    assert _TRACE_ID_PATTERN.fullmatch(problem["trace_id"])
    # context must never leak directly into the public problem body.
    assert "field" not in problem


def test_build_problem_gate_unavailable_is_fail_closed_shape() -> None:
    exc = GateUnavailableError("engine down")
    problem = build_problem(exc, instance="/v1/gate/authorize")
    assert problem["error_code"] == "saena.policy_denied.gate_unavailable"
    assert problem["retryable"] is False
    assert problem["status"] == 503


def test_build_problem_optional_tenant_and_run_id() -> None:
    exc = ValidationError("bad")
    problem = build_problem(exc, instance="/x", tenant_id="acme-co", run_id="run-1")
    assert problem["tenant_id"] == "acme-co"
    assert problem["run_id"] == "run-1"


def test_build_problem_omits_tenant_and_run_id_when_absent() -> None:
    exc = ValidationError("bad")
    problem = build_problem(exc, instance="/x")
    assert "tenant_id" not in problem
    assert "run_id" not in problem


def test_build_problem_uses_given_trace_id() -> None:
    exc = ValidationError("bad")
    problem = build_problem(exc, instance="/x", trace_id="a" * 32)
    assert problem["trace_id"] == "a" * 32
