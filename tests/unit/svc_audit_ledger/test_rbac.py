"""RBAC enforcement across every endpoint — default-deny (`saena_domain.authz`)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from ledger_factories import TENANT_A, make_append_body, roles_header


def test_append_without_append_audit_permission_is_403(client: TestClient) -> None:
    resp = client.post(
        "/v1/audit/entries", json=make_append_body(), headers=roles_header("auditor")
    )

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "saena.audit_ledger.rbac_denied"


def test_append_with_no_roles_header_is_403(client: TestClient) -> None:
    resp = client.post("/v1/audit/entries", json=make_append_body())

    assert resp.status_code == 403


def test_read_entries_without_read_audit_permission_is_403(client: TestClient) -> None:
    resp = client.get(
        "/v1/audit/entries",
        headers={**roles_header("service"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 403


def test_read_entries_with_read_audit_permission_succeeds(client: TestClient) -> None:
    resp = client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 200


@pytest.mark.parametrize(
    "role", ["operator", "service", "contracts_steward", "proposer", "approver"]
)
def test_lineage_denied_for_every_non_auditor_role(client: TestClient, role: str) -> None:
    ref = "audit:sha256:" + "0" * 64

    resp = client.get(f"/v1/audit/lineage/{ref}", headers=roles_header(role))

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "saena.audit_ledger.rbac_denied"


def test_lineage_denied_with_no_roles(client: TestClient) -> None:
    ref = "audit:sha256:" + "0" * 64

    resp = client.get(f"/v1/audit/lineage/{ref}")

    assert resp.status_code == 403


def test_unknown_role_token_is_ignored_not_granted(client: TestClient) -> None:
    """An unrecognized `X-Saena-Roles` token (typo, future role not yet in
    `Role`) is dropped rather than raising — `authz_boundary.roles_from_header`
    silently excludes it, which is equivalent to denial since it can never
    match `ALLOW_MATRIX`. Mixed with a real role to prove the KNOWN token is
    still honored alongside the dropped unknown one."""
    resp = client.get(
        "/v1/audit/entries",
        headers={
            "X-Saena-Roles": "not_a_real_role,auditor",
            "X-Saena-Tenant-Id": TENANT_A,
        },
    )

    assert resp.status_code == 200


def test_unknown_role_token_alone_grants_nothing(client: TestClient) -> None:
    resp = client.get(
        "/v1/audit/entries",
        headers={"X-Saena-Roles": "not_a_real_role", "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 403
