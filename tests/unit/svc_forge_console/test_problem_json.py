"""RFC 9457 `problem+json` response shape (ADR-0015) — covers FastAPI's own
422 request-validation path and human-actor-without-tenant rejection."""

from __future__ import annotations

from fastapi.testclient import TestClient
from saena_schemas.common.problem_detail_v1 import ProblemDetail

from svc_forge_console.conftest import actor_headers, run_create_body


def _assert_valid_problem_detail(body: dict[str, object]) -> None:
    # Round-trips through the generated ProblemDetail model -- proves the
    # body is not just "looks like RFC 9457" but is actually schema-valid
    # against the same contract every other service would validate against.
    ProblemDetail.model_validate(body)


class TestValidationErrorShape:
    def test_malformed_body_returns_422_problem_json(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json={"state": "not-a-real-state", "base_commit": "a" * 40},
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        _assert_valid_problem_detail(body)
        assert body["error_code"] == "saena.validation.schema_mismatch"
        assert body["status"] == 422
        assert body["retryable"] is False
        assert "trace_id" in body

    def test_missing_required_field_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json={"state": "INTAKE"},
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 422
        _assert_valid_problem_detail(response.json())

    def test_extra_field_is_rejected_extra_forbid(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json=run_create_body(unexpected_field="nope"),
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 422


class TestProblemJsonEverySeenErrorCategory:
    def test_403_permission_denied_is_valid_problem_detail(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs", json=run_create_body(), headers=actor_headers(roles=None)
        )
        _assert_valid_problem_detail(response.json())

    def test_404_not_found_is_valid_problem_detail(self, client: TestClient) -> None:
        response = client.get(
            "/v1/runs/019f5769-b226-7e4c-a6f7-6e0fa4c5ef56",
            headers=actor_headers(roles="proposer"),
        )
        _assert_valid_problem_detail(response.json())

    def test_401_auth_error_is_valid_problem_detail(self, client: TestClient) -> None:
        headers = actor_headers(roles=None)
        del headers["X-Saena-Session-Id"]
        response = client.get("/v1/actor/whoami", headers=headers)
        _assert_valid_problem_detail(response.json())


class TestHumanActorWithoutTenantRejected:
    def test_human_actor_without_tenant_id_is_rejected(self, client: TestClient) -> None:
        headers = actor_headers(actor_type="human", tenant_id=None, roles=None)
        response = client.get("/v1/actor/whoami", headers=headers)
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "saena.validation.actor_tenant_required"

    def test_system_actor_without_tenant_id_is_accepted(self, client: TestClient) -> None:
        headers = actor_headers(actor_type="system", tenant_id=None, roles=None)
        response = client.get("/v1/actor/whoami", headers=headers)
        assert response.status_code == 200
