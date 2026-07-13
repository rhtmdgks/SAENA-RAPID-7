"""Cross-tenant read isolation + tenant header validation."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ledger_factories import TENANT_A, TENANT_B, make_append_body, roles_header


def test_read_scoped_to_own_tenant_never_returns_other_tenants_entries(
    client: TestClient,
) -> None:
    client.post(
        "/v1/audit/entries",
        json=make_append_body(tenant_id=TENANT_A, payload={"patch_unit_id": "a-1"}),
        headers=roles_header("service"),
    )
    client.post(
        "/v1/audit/entries",
        json=make_append_body(tenant_id=TENANT_B, run_id="run-b", payload={"patch_unit_id": "b-1"}),
        headers=roles_header("service"),
    )

    resp_a = client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )
    resp_b = client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_B},
    )

    entries_a = resp_a.json()["entries"]
    entries_b = resp_b.json()["entries"]
    assert [e["payload"]["patch_unit_id"] for e in entries_a] == ["a-1"]
    assert [e["payload"]["patch_unit_id"] for e in entries_b] == ["b-1"]


def test_read_without_tenant_header_reads_system_scope_only(client: TestClient) -> None:
    client.post(
        "/v1/audit/entries",
        json=make_append_body(tenant_id=TENANT_A),
        headers=roles_header("service"),
    )
    client.post(
        "/v1/audit/entries",
        json=make_append_body(scope="system", tenant_id=None, run_id=None),
        headers=roles_header("service"),
    )

    resp = client.get("/v1/audit/entries", headers=roles_header("auditor"))

    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["scope"] == "system"


def test_malformed_tenant_header_is_rejected_with_400(client: TestClient) -> None:
    resp = client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": "NOT_VALID_!!"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "saena.identity.invalid_tenant_id"
