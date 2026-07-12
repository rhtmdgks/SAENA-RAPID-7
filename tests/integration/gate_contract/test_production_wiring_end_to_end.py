"""End-to-end production-wiring proof (w2-21 coordinated change): the REAL
`plan-contract-service` app, wired to the REAL `HttpPolicyGateClient` (no
test-only bridge/adapter — the exact class `saena_plan_contract.app`'s
`create_app(gate=...)` receives in production), reaches the REAL
`policy-gate-service` app over HTTP and completes a decision to APPROVED.

Distinct from `tests/integration/approval_flow/test_gate_wired.py`: that
suite (w2-14) proves the flow through `PlanContractHttpGateAdapter`, a
TEST-ONLY class that bridges `GateCheckRequest`'s old (caller-gap) shape to
policy-gate's real request schema BY HAND, precisely because — at the time
w2-14 ran — `app.py` did not yet populate `GateCheckRequest`'s H-3 fields
and `HttpPolicyGateClient` did not yet target the real route/shape/response
key (see `gate_client.py`'s own module docstring). This test proves that
bridge is no longer necessary: `submit_decision` -> `GateCheckRequest`
(now fully populated from `_PlanFacts`) -> `HttpPolicyGateClient`
(unmodified public class) -> real policy-gate app -> real `allow` -> real
`APPROVED` state, with NO test-side request-shape translation anywhere in
the path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gate_contract_factories import TENANT_ID
from saena_domain.persistence import InMemoryOutbox, InMemoryPlanRepository
from saena_plan_contract import create_app
from saena_plan_contract.gate_client import HttpPolicyGateClient
from saena_policy_gate.app import create_app as create_policy_gate_app

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "contract" / "fixtures" / "change-plan" / "valid"
_FIXTURE = _FIXTURE_DIR / "single-patch-unit.json"

PROPOSER_ACTOR_ID = "actor-proposer-0001"
APPROVER_ACTOR_ID = "actor-approver-0001"


def _load_change_plan() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["tenant_id"] = TENANT_ID
    return payload


def _decision_body(contract_hash: str, run_id: str, patch_unit_id: str) -> dict[str, Any]:
    return {
        "contract_hash": contract_hash,
        "tenant_id": TENANT_ID,
        "run_id": run_id,
        "approver_actor_id": APPROVER_ACTOR_ID,
        "decision": "approved",
        "patch_unit_decisions": [{"patch_unit_id": patch_unit_id, "decision": "approved"}],
        "signature": "sig-abc",
        "signature_algorithm": "ed25519",
        "decided_at": "2026-07-13T10:00:00Z",
    }


def test_submit_decision_reaches_approved_through_real_http_gate_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full production path, no test-only gate-request translation:
    `POST /v1/plans` -> `POST /v1/plans/{contract_hash}/decisions` on the
    REAL plan-contract app, whose `gate` dependency is the REAL,
    unmodified-signature `HttpPolicyGateClient`, talking to the REAL
    policy-gate app. Proves `app.py`'s `_PlanFacts` now carries everything
    `GateCheckRequest`/`PlanCheckRequestBody` need end to end."""
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_ID)

    policy_gate_app = create_policy_gate_app()
    policy_gate_client = TestClient(policy_gate_app, base_url="http://policy-gate")
    real_gate_client = HttpPolicyGateClient(
        "http://policy-gate", client=policy_gate_client, timeout=5.0
    )

    plan_contract_app = create_app(
        plans=InMemoryPlanRepository(),
        outbox=InMemoryOutbox(),
        gate=real_gate_client,
        tenant_env_value=TENANT_ID,
    )
    plan_contract_client = TestClient(plan_contract_app)

    change_plan = _load_change_plan()
    headers = {
        "X-Saena-Tenant-Id": TENANT_ID,
        "X-Saena-Actor-Id": PROPOSER_ACTOR_ID,
    }

    propose_response = plan_contract_client.post("/v1/plans", json=change_plan, headers=headers)
    assert propose_response.status_code == 201
    contract_hash = propose_response.json()["contract_hash"]
    assert propose_response.json()["state"] == "waiting_approval"

    patch_unit_id = change_plan["patch_units"][0]["id"]
    decision_response = plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=_decision_body(
            contract_hash, run_id=change_plan["run_id"], patch_unit_id=patch_unit_id
        ),
        headers=headers,
    )

    assert decision_response.status_code == 200, decision_response.text
    assert decision_response.json()["state"] == "approved"

    state_response = plan_contract_client.get(f"/v1/plans/{contract_hash}", headers=headers)
    assert state_response.status_code == 200
    assert state_response.json()["state"] == "approved"
    assert state_response.json()["decisions"][0]["decision"] == "approved"

    plan_contract_client.close()
    policy_gate_client.close()
    real_gate_client.close()
