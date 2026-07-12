"""W2A exit condition 5 — cross-tenant + tenant-boundary enforcement across
the wired services: a run/plan in tenant A cannot be approved/read with
tenant B credentials (403). Header/env reconciliation enforced at each of
the three services this unit wires (plan-contract, policy-gate,
forge-console).

`plan-contract-service` pins its tenant reconciliation target
(`tenant_env_value`) at `create_app()` construction time (a Pod-scoped
value, not a live env var read per request — see `harness.py` module
docstring) — the `harness` fixture's single app is permanently bound to
`TENANT_A`; every cross-tenant assertion against it is therefore "does
tenant B's header get rejected by THIS tenant-A-pinned pod", exactly the
real k3s deployment shape (one pod per tenant, ADR-0014). `policy-gate-
service`/`forge-console-api` instead reconcile against the PROCESS
`SAENA_TENANT_ID` env var read at request time, so this module also proves
the boundary holds when a SECOND, differently-tenant-scoped pod (a second
harness instance) exists in parallel, without cross-tenant leakage through
either services' own in-memory store.
"""

from __future__ import annotations

import pytest
from approval_factories import TENANT_A, TENANT_B, decision_body
from approval_harness import ApprovalFlowHarness, build_harness


def _propose(harness: ApprovalFlowHarness, headers: dict[str, str], change_plan: dict) -> str:
    response = harness.plan_contract_client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    return response.json()["contract_hash"]


def test_plan_contract_rejects_mismatched_tenant_header_on_decision(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    """`harness` is pinned to TENANT_A (`tenant_env_value=TENANT_A`) — a
    caller presenting TENANT_B's header against this SAME pod is rejected
    before ever reaching the decision route (ADR-0014 tenant reconciliation,
    services-layer 403, not merely a 404/empty result)."""
    contract_hash = _propose(harness, proposer_headers, change_plan)

    tenant_b_headers = {"X-Saena-Tenant-Id": TENANT_B, "X-Saena-Actor-Id": "actor-approver-0001"}
    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"], tenant_id=TENANT_B),
        headers=tenant_b_headers,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.auth.tenant_mismatch"


def test_plan_contract_rejects_mismatched_tenant_header_on_read(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    contract_hash = _propose(harness, proposer_headers, change_plan)

    response = harness.plan_contract_client.get(
        f"/v1/plans/{contract_hash}", headers={"X-Saena-Tenant-Id": TENANT_B}
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.auth.tenant_mismatch"


def test_two_tenant_pods_do_not_leak_plans_across_shared_process_env(
    monkeypatch: pytest.MonkeyPatch, change_plan: dict
) -> None:
    """Two SEPARATE harnesses (simulating two tenant-scoped pods) each pinned
    to their own tenant — tenant B's plan-contract pod never sees tenant A's
    plan, and vice versa, even though both ran in the same test process."""
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_A)
    harness_a = build_harness(tenant_id=TENANT_A)
    try:
        contract_hash = _propose(
            harness_a,
            {"X-Saena-Tenant-Id": TENANT_A, "X-Saena-Actor-Id": "actor-proposer-0001"},
            change_plan,
        )

        monkeypatch.setenv("SAENA_TENANT_ID", TENANT_B)
        harness_b = build_harness(tenant_id=TENANT_B)
        try:
            # Tenant B's OWN pod, reading its OWN (empty) plan repository,
            # has never heard of tenant A's contract_hash.
            response = harness_b.plan_contract_client.get(
                f"/v1/plans/{contract_hash}", headers={"X-Saena-Tenant-Id": TENANT_B}
            )
            assert response.status_code == 404
            assert response.json()["error_code"] == "saena.not_found.resource_missing"
        finally:
            harness_b.close()
    finally:
        harness_a.close()


def test_forge_console_run_created_under_tenant_a_not_readable_via_tenant_b_header(
    harness: ApprovalFlowHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """forge-console-api's `RunStore` is tenant-scoped even though the SAME
    process/app instance serves every tenant (unlike plan-contract's
    per-pod-pinned model) — a request presenting TENANT_B's header against
    the SAME `SAENA_TENANT_ID=TENANT_A` pod is rejected at the
    tenant-reconciliation middleware (403), never reaching `RunStore`."""
    create_response = harness.forge_console_client.post(
        "/v1/runs",
        json={"state": "INTAKE", "base_commit": "a" * 40, "human_approval_required": True},
        headers={
            "X-Saena-Actor-Id": "actor-proposer-0001",
            "X-Saena-Session-Id": "session-0001",
            "X-Saena-Actor-Type": "human",
            "X-Saena-Tenant-Id": TENANT_A,
            "X-Saena-Roles": "proposer",
        },
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["run_id"]

    mismatched_response = harness.forge_console_client.get(
        f"/v1/runs/{run_id}",
        headers={
            "X-Saena-Actor-Id": "actor-proposer-0001",
            "X-Saena-Session-Id": "session-0001",
            "X-Saena-Actor-Type": "human",
            "X-Saena-Tenant-Id": TENANT_B,
            "X-Saena-Roles": "proposer",
        },
    )
    assert mismatched_response.status_code == 403
    assert mismatched_response.json()["error_code"] == "saena.policy_denied.tenant_mismatch"


def test_forge_console_run_isolated_across_reconciled_second_tenant_pod(
    harness: ApprovalFlowHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `RunStore`-level isolation check specifically: BOTH requests
    reconcile successfully (their own header always matches
    `SAENA_TENANT_ID` at request time, simulating two separate pods sharing
    the SAME `RunStore` — mirrors
    `tests/unit/svc_forge_console/test_run_routes.py`'s own precedent), so a
    cross-tenant read reaches `RunStore`'s OWN tenant-ownership check,
    surfaced as 404 (never a 403 that would confirm the run_id exists under
    a different tenant)."""
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_A)
    created = harness.forge_console_client.post(
        "/v1/runs",
        json={"state": "INTAKE", "base_commit": "a" * 40, "human_approval_required": True},
        headers={
            "X-Saena-Actor-Id": "actor-proposer-0001",
            "X-Saena-Session-Id": "session-0001",
            "X-Saena-Actor-Type": "human",
            "X-Saena-Tenant-Id": TENANT_A,
            "X-Saena-Roles": "proposer",
        },
    ).json()

    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_B)
    response = harness.forge_console_client.get(
        f"/v1/runs/{created['run_id']}",
        headers={
            "X-Saena-Actor-Id": "actor-proposer-0001",
            "X-Saena-Session-Id": "session-0001",
            "X-Saena-Actor-Type": "human",
            "X-Saena-Tenant-Id": TENANT_B,
            "X-Saena-Roles": "proposer",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.resource_missing"
