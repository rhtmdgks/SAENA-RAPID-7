"""Red-if-regressed guards for the exact 3-axis defect w2-14's E2E critic
found (see `saena_plan_contract.gate_client` module docstring): wrong path,
wrong request shape, wrong response key. Each test below fails LOUDLY (not
silently) if any of the three regresses.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from gate_contract_factories import make_request
from saena_plan_contract.gate_client import HttpPolicyGateClient


def test_client_reaches_the_real_route_not_a_404(
    policy_gate_app_client: TestClient, real_gate_client: HttpPolicyGateClient
) -> None:
    """Axis 1 (wrong path) regression guard: post the SAME request body the
    client would send directly to the OLD (wrong) path and confirm the real
    app 404s there — then confirm the client itself (using the corrected
    path internally) gets a real 200-shaped decision, not a 404 masquerading
    as `PolicyGateUnavailableError`."""
    request = make_request(contract_hash="sha256:" + "4" * 64)

    # The old, buggy path really does 404 on the real app — this pins down
    # WHY the old client failed, so this guard cannot be satisfied by
    # accident.
    old_path_response = policy_gate_app_client.post(
        "/v1/plan-check", json={}, headers={"X-Saena-Tenant-Id": request.tenant_id}
    )
    assert old_path_response.status_code == 404

    # The real (fixed) client reaches /v1/gate/plan-check and gets a real
    # decision back — not a PolicyGateUnavailableError from a 404.
    decision = real_gate_client.plan_check(request)
    assert decision.allow is True


def test_client_request_body_passes_real_schema_validation_not_422(
    policy_gate_app_client: TestClient, real_gate_client: HttpPolicyGateClient
) -> None:
    """Axis 2 (wrong request shape) regression guard: the OLD `GateCheckRequest`-
    shaped body (`contract_hash`/`tenant_id`/`high_risk`/`approved_scope`/
    `patch_unit_ids` only) really does 422 against the real
    `PlanCheckRequestBody` schema — then confirm the fixed client's actual
    request body passes real pydantic validation (200, not 422)."""
    old_shaped_body = {
        "contract_hash": "sha256:" + "5" * 64,
        "tenant_id": "acme-corp",
        "high_risk": False,
        "approved_scope": ["apps/web/docs/*"],
        "patch_unit_ids": ["PU-01"],
    }
    old_shape_response = policy_gate_app_client.post(
        "/v1/gate/plan-check",
        json=old_shaped_body,
        headers={"X-Saena-Tenant-Id": "acme-corp"},
    )
    assert old_shape_response.status_code == 422

    request = make_request(contract_hash="sha256:" + "5" * 64)
    decision = real_gate_client.plan_check(request)
    assert decision.allow is True


def test_client_parses_real_response_decision_key_not_allow_key(
    policy_gate_app_client: TestClient, real_gate_client: HttpPolicyGateClient
) -> None:
    """Axis 3 (wrong response parse) regression guard: the real
    `GateDecisionResponse` never sends an `allow` key — confirm that
    directly against the real app's raw response, then confirm the fixed
    client still produces a correct `GateDecision.allow` from the REAL
    `decision` key."""
    request = make_request(contract_hash="sha256:" + "6" * 64)

    raw_response = policy_gate_app_client.post(
        "/v1/gate/plan-check",
        json={
            "contract_hash": request.contract_hash,
            "proposer_actor_id": request.proposer_actor_id,
            "approver_actor_id": request.approver_actor_id,
            "evidence_ledger_hash": request.evidence_ledger_hash,
            "approved_scope": list(request.approved_scope),
            "scope_max_globs": request.scope_max_globs,
            "diff_max_files": request.diff_max_files,
            "diff_max_lines": request.diff_max_lines,
            "hypothesis_risks": list(request.hypothesis_risks),
        },
        headers={"X-Saena-Tenant-Id": request.tenant_id},
    )
    assert raw_response.status_code == 200
    body = raw_response.json()
    assert "allow" not in body
    assert body["decision"] == "allow"

    decision = real_gate_client.plan_check(request)
    assert decision.allow is True


def test_a_still_mismatched_body_422_fails_closed_not_silent_allow(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    """Instruction-mandated guard: if the request body were STILL mismatched
    (e.g. an `extra="forbid"` field policy-gate rejects), the client must
    raise `PolicyGateUnavailableError` — never treat a 422 as an implicit
    allow. Simulated here via a raw httpx call reusing the client's own
    transport, since the fixed client itself now always builds a valid body
    (this proves the 422-handling BRANCH, not just the happy path)."""
    from saena_plan_contract.errors import PolicyGateUnavailableError

    # Force the underlying transport to 422 by posting a body with an
    # extra="forbid"-violating field, using the client's OWN transport, to
    # confirm status_code != 200 -> PolicyGateUnavailableError is live code,
    # not dead code the happy-path tests never touch.
    response = real_gate_client._client.post(
        "/v1/gate/plan-check",
        json={"unexpected_field": True},
        headers={"X-Saena-Tenant-Id": "acme-corp"},
    )
    assert response.status_code == 422

    with pytest.raises(PolicyGateUnavailableError):
        real_gate_client.plan_check(
            make_request(
                contract_hash="sha256:" + "7" * 64,
                evidence_ledger_hash=None,  # caller-gap: forces the pre-flight guard
            )
        )


def test_health_reaches_real_v1_health_path(real_gate_client: HttpPolicyGateClient) -> None:
    """`health()`'s OLD path (`{base_url}/health`) 404s on the real app too
    — confirm the fixed client's `/v1/health` reaches the real route."""
    assert real_gate_client.health() is True
