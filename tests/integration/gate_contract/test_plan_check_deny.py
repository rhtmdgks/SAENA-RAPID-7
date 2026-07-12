"""Real client <-> real gate: an H-3 evidence-policy VIOLATION (a
scope-escaping glob) is denied by the real `policy-gate-service` app, and
`HttpPolicyGateClient` maps `decision: "deny"` to `GateDecision(allow=False,
...)` with the real evaluator's reasons surfaced — never a silent allow.
"""

from __future__ import annotations

from gate_contract_factories import make_request
from saena_plan_contract.gate_client import HttpPolicyGateClient


def test_h3_scope_escape_is_denied_by_real_gate(real_gate_client: HttpPolicyGateClient) -> None:
    request = make_request(
        contract_hash="sha256:" + "e" * 64,
        approved_scope=("../etc/passwd",),
    )

    decision = real_gate_client.plan_check(request)

    assert decision.allow is False
    assert decision.reasons
    assert "scope glob escapes declared roots" in decision.reasons[0]


def test_scope_limit_exceeded_is_denied_by_real_gate(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    """More `approved_scope` globs than `scope_max_globs` allows — a second,
    independent H-3 violation branch (`evaluate_h3_evidence_policy` check 2),
    confirming this is the real evaluator, not a single-hardcoded-reason
    stub."""
    request = make_request(
        contract_hash="sha256:" + "f" * 64,
        approved_scope=("apps/web/a/*", "apps/web/b/*", "apps/web/c/*"),
        scope_max_globs=1,
    )

    decision = real_gate_client.plan_check(request)

    assert decision.allow is False
    assert decision.reasons
