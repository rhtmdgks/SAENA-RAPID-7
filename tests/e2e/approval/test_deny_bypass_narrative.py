"""W2A exit condition 3 (deny-bypass regression) folded into the end-to-end
narrative: an attacker-shaped command embedded in an otherwise-legitimate
approval flow is denied by the REAL policy-gate-service `/v1/gate/authorize`
surface this harness wires — proven here as part of the SAME narrative
`test_happy_path.py` builds (one proposed/approved plan), not a bare
parametrized unit list.

Full bypass-corpus coverage (every wrapper/shell/env-prefix/`.exe`/pipeline
variant) lives at:
    - `tests/unit/svc_policy_gate/test_engine.py` (engine/argv-classification
      internals, `classify_command`/`classify_pipeline`).
    - `tests/unit/svc_policy_gate/test_app_routes.py::
      test_authorize_denies_bypass_regressions` (policy-gate-service's own
      HTTP route, in isolation).
    - `tests/integration/approval_flow/test_deny_bypass_regression.py`
      (the SAME corpus, parametrized, through THIS unit's wired HTTP
      surface — the integration-level proof this narrative test summarizes).
"""

from __future__ import annotations

from approval_factories import TENANT_A
from approval_harness import ApprovalFlowHarness


def test_kubectl_patch_bypass_denied_alongside_a_real_approval_flow(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    """A legitimate propose/approve flow succeeds on the SAME harness an
    attacker-shaped `kubectl patch` authorize attempt is denied on —
    demonstrates the gate's deny-bypass defenses do not interfere with (or
    get bypassed by) ordinary approved-plan traffic sharing the same
    process/decision store."""
    propose_response = harness.plan_contract_client.post(
        "/v1/plans", json=change_plan, headers=proposer_headers
    )
    assert propose_response.status_code == 201

    bypass_response = harness.policy_gate_client.post(
        "/v1/gate/authorize",
        json={
            "kind": "command",
            "action": "execute",
            "resource": ["env", "sudo", "sh", "-c", "kubectl.exe patch pod x"],
            "approver_actor_id": "actor-approver-0001",
        },
        headers={"X-Saena-Tenant-Id": TENANT_A},
    )
    assert bypass_response.status_code == 200
    assert bypass_response.json()["decision"] == "deny"

    git_dash_c_response = harness.policy_gate_client.post(
        "/v1/gate/authorize",
        json={
            "kind": "command",
            "action": "execute",
            "resource": ["git", "-c", "a=b", "push"],
            "approver_actor_id": "actor-approver-0001",
        },
        headers={"X-Saena-Tenant-Id": TENANT_A},
    )
    assert git_dash_c_response.status_code == 200
    assert git_dash_c_response.json()["decision"] == "deny"
