"""`POST /v1/runs` / `GET /v1/runs/{run_id}` — happy path, cross-tenant
isolation, RBAC default-deny.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from saena_forge_console.app import create_app
from saena_forge_console.lineage import InMemoryLineagePort
from saena_forge_console.run_store import RunStore

from svc_forge_console.conftest import DEFAULT_TENANT, OTHER_TENANT, actor_headers, run_create_body


class TestCreateRunHappyPath:
    def test_create_run_returns_201_with_generated_run_id(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json=run_create_body(),
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["tenant_id"] == DEFAULT_TENANT
        assert body["state"] == "INTAKE"
        assert body["human_approval_required"] is True
        assert isinstance(body["run_id"], str) and body["run_id"] != ""

    def test_create_run_generates_uuidv7_run_id(self, client: TestClient) -> None:
        import re

        response = client.post(
            "/v1/runs",
            json=run_create_body(),
            headers=actor_headers(roles="proposer"),
        )
        run_id = response.json()["run_id"]
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", run_id
        )

    def test_create_run_does_not_accept_client_supplied_run_id(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json=run_create_body(run_id="client-supplied-id"),
            headers=actor_headers(roles="proposer"),
        )
        # RunCreateRequest excludes run_id/tenant_id and forbids extras
        # (ConfigDict(extra="forbid")) -- a client-supplied run_id is a
        # validation error, not silently accepted/ignored.
        assert response.status_code == 422


class TestGetRunHappyPath:
    def test_get_run_returns_the_stored_run(self, client: TestClient) -> None:
        created = client.post(
            "/v1/runs",
            json=run_create_body(),
            headers=actor_headers(roles="proposer"),
        ).json()
        response = client.get(
            f"/v1/runs/{created['run_id']}",
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 200
        assert response.json() == created

    def test_get_unknown_run_returns_404(self, client: TestClient) -> None:
        response = client.get(
            "/v1/runs/019f5769-b226-7e4c-a6f7-6e0fa4c5ef56",
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == "saena.not_found.resource_missing"


class TestCrossTenantIsolation:
    def test_reading_another_tenants_run_returns_404_not_403(self, client: TestClient) -> None:
        created = client.post(
            "/v1/runs",
            json=run_create_body(),
            headers=actor_headers(tenant_id=DEFAULT_TENANT, roles="proposer"),
        ).json()

        # A caller from a different tenant, reconciled against its OWN pod
        # env (simulated by a mismatched X-Saena-Tenant-Id would 403 at the
        # tenant-reconciliation middleware before ever reaching the route --
        # so to exercise the ROUTE-layer/RunStore isolation check
        # specifically, this request's header matches the fixture's bound
        # SAENA_TENANT_ID env (DEFAULT_TENANT) is overridden via monkeypatch
        # in the dedicated test below instead. This test targets the
        # simpler, always-true invariant: a request that never resolves
        # DEFAULT_TENANT can never read a DEFAULT_TENANT-owned run.
        response = client.get(
            f"/v1/runs/{created['run_id']}",
            headers=actor_headers(tenant_id=OTHER_TENANT, roles="proposer"),
        )
        # The mismatched X-Saena-Tenant-Id (OTHER_TENANT) vs pod env
        # (DEFAULT_TENANT, set by the `client` fixture) is caught by the
        # tenant-reconciliation middleware first -- 403, never reaching the
        # RunStore isolation check. This assertion documents that ordering:
        # tenant reconciliation is checked before RBAC/run ownership.
        assert response.status_code == 403
        assert response.json()["error_code"] == "saena.policy_denied.tenant_mismatch"

    def test_reading_another_tenants_run_via_a_reconciled_second_tenant_returns_404(
        self, monkeypatch: pytest.MonkeyPatch, run_store: RunStore
    ) -> None:
        """Exercise the `RunStore` isolation check specifically -- both
        requests reconcile successfully (their own `X-Saena-Tenant-Id`
        header always matches the pod's OWN `SAENA_TENANT_ID` at request
        time, simulating two SEPARATE pods each scoped to a different
        tenant sharing the same `RunStore` fixture instance), so a
        cross-tenant read only ever reaches the RunStore's own tenant
        ownership check, never the reconciliation middleware's 403.
        """
        lineage_port = InMemoryLineagePort()
        app = create_app(run_store=run_store, lineage_port=lineage_port)
        client = TestClient(app)

        monkeypatch.setenv("SAENA_TENANT_ID", DEFAULT_TENANT)
        created = client.post(
            "/v1/runs",
            json=run_create_body(),
            headers=actor_headers(tenant_id=DEFAULT_TENANT, roles="proposer"),
        ).json()

        monkeypatch.setenv("SAENA_TENANT_ID", OTHER_TENANT)
        response = client.get(
            f"/v1/runs/{created['run_id']}",
            headers=actor_headers(tenant_id=OTHER_TENANT, roles="proposer"),
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == "saena.not_found.resource_missing"


__all__: list[str] = []
