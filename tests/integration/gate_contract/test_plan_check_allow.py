"""Real client <-> real gate: a schema-valid, H-3-satisfying request is
allowed by the real `policy-gate-service` app, and `HttpPolicyGateClient`
correctly maps the response to `GateDecision(allow=True, ...)`.
"""

from __future__ import annotations

from gate_contract_factories import make_request
from saena_plan_contract.gate_client import HttpPolicyGateClient


def test_valid_plan_check_request_is_allowed_by_real_gate(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    request = make_request(contract_hash="sha256:" + "c" * 64)

    decision = real_gate_client.plan_check(request)

    assert decision.allow is True
    assert decision.require_two_person is False


def test_allow_decision_reasons_come_from_real_h3_evaluator(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    """`GateDecision.reasons` on the allow path is the REAL
    `evaluate_h3_evidence_policy` "satisfied" message (`service.py`
    `check_plan`'s `_evaluate` closure), not a canned client-side string —
    proves the response body is genuinely parsed, not defaulted."""
    request = make_request(contract_hash="sha256:" + "d" * 64)

    decision = real_gate_client.plan_check(request)

    assert decision.reasons == ("H-3 evidence policy satisfied",)
