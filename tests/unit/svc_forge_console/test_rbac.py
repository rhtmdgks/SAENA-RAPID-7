"""RBAC default-deny: no `X-Saena-Roles` header (or an unrelated role) ->
403 on every permission-gated route."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from svc_forge_console.conftest import actor_headers, run_create_body


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/v1/runs", run_create_body()),
        ("GET", "/v1/runs/019f5769-b226-7e4c-a6f7-6e0fa4c5ef56", None),
        ("GET", "/v1/lineage/audit:sha256:" + "a" * 64, None),
    ],
)
def test_no_roles_header_denies_every_gated_route(
    client: TestClient, method: str, path: str, json_body: dict[str, object] | None
) -> None:
    response = client.request(method, path, json=json_body, headers=actor_headers(roles=None))
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.permission_denied"


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/v1/runs", run_create_body()),
        ("GET", "/v1/runs/019f5769-b226-7e4c-a6f7-6e0fa4c5ef56", None),
        ("GET", "/v1/lineage/audit:sha256:" + "a" * 64, None),
    ],
)
def test_unrelated_role_denies_every_gated_route(
    client: TestClient, method: str, path: str, json_body: dict[str, object] | None
) -> None:
    # "service" only holds append_audit -- none of these three routes.
    response = client.request(method, path, json=json_body, headers=actor_headers(roles="service"))
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.permission_denied"


class TestLineageAuditorGate:
    def test_operator_is_denied_lineage(self, client: TestClient) -> None:
        response = client.get(
            "/v1/lineage/audit:sha256:" + "a" * 64,
            headers=actor_headers(roles="operator"),
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "saena.policy_denied.permission_denied"

    def test_proposer_is_denied_lineage(self, client: TestClient) -> None:
        response = client.get(
            "/v1/lineage/audit:sha256:" + "a" * 64,
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 403


class TestWhoamiHasNoRbacGate:
    def test_whoami_succeeds_with_no_roles_header(self, client: TestClient) -> None:
        response = client.get("/v1/actor/whoami", headers=actor_headers(roles=None))
        assert response.status_code == 200
