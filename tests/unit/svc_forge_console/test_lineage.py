"""`GET /v1/lineage/{ref}` — auditor-only RBAC edge gate BEFORE any
downstream (stubbed) call."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from saena_forge_console.app import create_app
from saena_forge_console.lineage import InMemoryLineagePort
from saena_forge_console.run_store import RunStore

from svc_forge_console.conftest import DEFAULT_TENANT, actor_headers

_REF = "audit:sha256:" + "a" * 64


def test_auditor_gets_200_with_stubbed_downstream_record(
    monkeypatch: pytest.MonkeyPatch,
    lineage_port: InMemoryLineagePort,
    run_store: RunStore,
) -> None:
    monkeypatch.setenv("SAENA_TENANT_ID", DEFAULT_TENANT)
    lineage_port.seed(DEFAULT_TENANT, _REF, {"ref": _REF, "resolved": True})
    app = create_app(run_store=run_store, lineage_port=lineage_port)
    client = TestClient(app)

    response = client.get(f"/v1/lineage/{_REF}", headers=actor_headers(roles="auditor"))
    assert response.status_code == 200
    assert response.json() == {"ref": _REF, "resolved": True}


def test_operator_gets_403_before_any_downstream_call(client: TestClient) -> None:
    response = client.get(f"/v1/lineage/{_REF}", headers=actor_headers(roles="operator"))
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.permission_denied"


def test_auditor_unknown_ref_returns_404(client: TestClient) -> None:
    response = client.get(f"/v1/lineage/{_REF}", headers=actor_headers(roles="auditor"))
    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.resource_missing"


def test_stub_lineage_port_always_404s_when_no_port_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAENA_TENANT_ID", DEFAULT_TENANT)
    app = create_app()
    client = TestClient(app)
    response = client.get(f"/v1/lineage/{_REF}", headers=actor_headers(roles="auditor"))
    assert response.status_code == 404
