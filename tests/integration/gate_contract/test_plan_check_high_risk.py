"""Real client <-> real gate: `high_risk=True` is surfaced as
`require_two_person=True` on the parsed `GateDecision` — proves
`GateDecisionResponse.require_two_person` (not just `decision`) round-trips
through `HttpPolicyGateClient.plan_check`'s response parsing.
"""

from __future__ import annotations

from gate_contract_factories import make_request
from saena_plan_contract.gate_client import HttpPolicyGateClient


def test_high_risk_request_surfaces_require_two_person(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    request = make_request(
        contract_hash="sha256:" + "1" * 64,
        high_risk=True,
        hypothesis_risks=("high",),
    )

    decision = real_gate_client.plan_check(request)

    assert decision.allow is True
    assert decision.require_two_person is True


def test_low_risk_request_does_not_require_two_person(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    request = make_request(
        contract_hash="sha256:" + "2" * 64,
        high_risk=False,
        hypothesis_risks=("low",),
    )

    decision = real_gate_client.plan_check(request)

    assert decision.allow is True
    assert decision.require_two_person is False


def test_high_risk_denial_still_surfaces_require_two_person(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    """`require_two_person` derives from `high_risk` alone in
    `service.py::check_plan` (`high_risk = is_high_risk_plan(...)`, passed
    straight through `_evaluate_and_record` regardless of the H-3 evaluation
    outcome) — this must hold on a DENY response too, not just an allow."""
    request = make_request(
        contract_hash="sha256:" + "3" * 64,
        high_risk=True,
        hypothesis_risks=("high",),
        approved_scope=("../etc/passwd",),
    )

    decision = real_gate_client.plan_check(request)

    assert decision.allow is False
    assert decision.require_two_person is True
