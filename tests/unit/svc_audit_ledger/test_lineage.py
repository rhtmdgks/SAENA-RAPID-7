"""GET /v1/audit/lineage/{lineage_ref} — auditor-only resolution (ADR-0013)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ledger_factories import TENANT_A, make_append_body, roles_header
from saena_domain.audit import make_lineage_ref


def _append_and_get_hash(client: TestClient) -> str:
    resp = client.post(
        "/v1/audit/entries", json=make_append_body(), headers=roles_header("service")
    )
    event_hash: str = resp.json()["event_hash"]
    return event_hash


def test_auditor_resolves_lineage_ref_with_tenant_header(client: TestClient) -> None:
    event_hash = _append_and_get_hash(client)
    ref = make_lineage_ref(event_hash)

    resp = client.get(
        f"/v1/audit/lineage/{ref}",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 200
    assert resp.json()["event_hash"] == event_hash


def test_auditor_resolves_system_scope_lineage_ref_without_tenant_header(
    client: TestClient,
) -> None:
    resp = client.post(
        "/v1/audit/entries",
        json=make_append_body(scope="system", tenant_id=None, run_id=None),
        headers=roles_header("service"),
    )
    event_hash = resp.json()["event_hash"]
    ref = make_lineage_ref(event_hash)

    lineage_resp = client.get(f"/v1/audit/lineage/{ref}", headers=roles_header("auditor"))

    assert lineage_resp.status_code == 200
    assert lineage_resp.json()["event_hash"] == event_hash


def test_operator_is_denied_lineage_even_with_valid_ref(client: TestClient) -> None:
    event_hash = _append_and_get_hash(client)
    ref = make_lineage_ref(event_hash)

    resp = client.get(
        f"/v1/audit/lineage/{ref}",
        headers={**roles_header("operator"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 403


def test_service_is_denied_lineage(client: TestClient) -> None:
    event_hash = _append_and_get_hash(client)
    ref = make_lineage_ref(event_hash)

    resp = client.get(
        f"/v1/audit/lineage/{ref}",
        headers={**roles_header("service"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 403


def test_contracts_steward_is_denied_lineage(client: TestClient) -> None:
    event_hash = _append_and_get_hash(client)
    ref = make_lineage_ref(event_hash)

    resp = client.get(
        f"/v1/audit/lineage/{ref}",
        headers={**roles_header("contracts_steward"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 403


def test_lineage_with_garbage_ref_is_400(client: TestClient) -> None:
    resp = client.get(
        "/v1/audit/lineage/not-a-real-ref",
        headers=roles_header("auditor"),
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "saena.audit_ledger.invalid_lineage_ref"


def test_lineage_with_well_formed_but_unknown_ref_is_404(client: TestClient) -> None:
    unknown_ref = "audit:sha256:" + "a" * 64

    resp = client.get(
        f"/v1/audit/lineage/{unknown_ref}",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 404
    assert resp.json()["error_code"] == "saena.audit_ledger.lineage_ref_not_found"
