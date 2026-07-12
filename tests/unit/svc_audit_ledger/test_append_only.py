"""Append-only enforcement: no update/delete route exists (README "immutable role access")."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ledger_factories import make_append_body, roles_header
from saena_audit_ledger.app import create_app
from saena_domain.persistence import InMemoryAuditLedger


def test_put_on_entries_is_rejected(client: TestClient) -> None:
    resp = client.put("/v1/audit/entries", json={}, headers=roles_header("service"))

    assert resp.status_code == 405


def test_delete_on_entries_is_rejected(client: TestClient) -> None:
    resp = client.delete("/v1/audit/entries", headers=roles_header("service"))

    assert resp.status_code == 405


def test_put_does_not_mutate_an_existing_entry(client: TestClient) -> None:
    posted = client.post(
        "/v1/audit/entries", json=make_append_body(), headers=roles_header("service")
    ).json()

    client.put(
        "/v1/audit/entries",
        json={"payload": {"patch_unit_id": "mutated"}},
        headers=roles_header("service"),
    )

    resp = client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": posted["tenant_id"]},
    )
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["payload"] == {"patch_unit_id": "w2-10-audit-ledger"}


def test_no_update_delete_routes_exist_on_any_audit_path() -> None:
    """Route-table inspection (not merely probing PUT/DELETE on one path):
    no route registered under `/v1/audit/**` accepts PUT/PATCH/DELETE."""
    app = create_app(InMemoryAuditLedger())
    mutating_methods = {"PUT", "PATCH", "DELETE"}

    offending: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if not path.startswith("/v1/audit/"):
            continue
        for method in methods & mutating_methods:
            # The one deliberate exception: PUT/DELETE on /v1/audit/entries
            # are registered ON PURPOSE to return 405 (explicit rejection,
            # not merely FastAPI's default "no route" 404) — every other
            # audit path must have NO mutating method registered at all.
            if path == "/v1/audit/entries" and method in {"PUT", "DELETE"}:
                continue
            offending.append((method, path))

    assert offending == []
