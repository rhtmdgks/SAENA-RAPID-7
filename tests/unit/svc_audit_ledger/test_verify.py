"""GET /v1/audit/verify — chain integrity + tamper detection."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ledger_factories import TENANT_A, make_append_body, roles_header
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryAuditLedger


def test_verify_ok_on_empty_chain(client: TestClient) -> None:
    resp = client.get(
        "/v1/audit/verify",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "first_broken_index": None}


def test_verify_ok_after_several_appends(client: TestClient) -> None:
    for i in range(3):
        client.post(
            "/v1/audit/entries",
            json=make_append_body(payload={"patch_unit_id": f"unit-{i}"}),
            headers=roles_header("service"),
        )

    resp = client.get(
        "/v1/audit/verify",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.json() == {"ok": True, "first_broken_index": None}


def test_verify_reports_broken_index_after_direct_tamper(
    client: TestClient, ledger: InMemoryAuditLedger
) -> None:
    """Tamper simulation via direct port access (white-box, mirrors
    `tests/unit/domain_persistence/test_audit_ledger.py`'s own technique) —
    the HTTP layer has no mutation endpoint of its own, so this reaches into
    the injected `ledger` fixture directly to prove `verify` genuinely
    detects corruption rather than trivially always passing."""
    client.post(
        "/v1/audit/entries",
        json=make_append_body(payload={"patch_unit_id": "unit-0"}),
        headers=roles_header("service"),
    )
    client.post(
        "/v1/audit/entries",
        json=make_append_body(payload={"patch_unit_id": "unit-1"}),
        headers=roles_header("service"),
    )

    stored = ledger._tenant_chains[TENANT_A]  # noqa: SLF001
    tampered = stored[0].model_copy(update={"payload": {"patch_unit_id": "tampered"}})
    stored[0] = tampered

    resp = client.get(
        "/v1/audit/verify",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.json() == {"ok": False, "first_broken_index": 0}


def test_verify_requires_read_audit_permission(client: TestClient) -> None:
    resp = client.get(
        "/v1/audit/verify",
        headers={**roles_header("operator"), "X-Saena-Tenant-Id": TENANT_A},
    )

    assert resp.status_code == 403


def test_verify_system_scope_independent_of_tenant_scope(
    client: TestClient, ledger: InMemoryAuditLedger
) -> None:
    client.post(
        "/v1/audit/entries",
        json=make_append_body(scope="system", tenant_id=None, run_id=None),
        headers=roles_header("service"),
    )

    ok, index = ledger.verify(tenant_id=TenantId(TENANT_A))
    assert ok is True and index is None

    resp = client.get("/v1/audit/verify", headers=roles_header("auditor"))
    assert resp.json() == {"ok": True, "first_broken_index": None}
