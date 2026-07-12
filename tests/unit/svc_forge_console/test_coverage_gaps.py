"""Direct unit tests for module-level branches not naturally reachable
through a full HTTP round-trip (defensive fallbacks, unused-by-routes error
constructors, low-level store/trace edge cases)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from saena_forge_console.authn import build_request_actor
from saena_forge_console.errors import (
    ErrorCategory,
    ServiceError,
    internal_error,
    to_problem_detail,
)
from saena_forge_console.run_store import RunStore, RunTenantIsolationError
from saena_forge_console.trace import resolve_trace_id
from saena_schemas.context.run_context_lifecycle_v1 import RuncontextLifecycle

from svc_forge_console.conftest import actor_headers


class TestInternalError:
    def test_internal_error_builds_500_service_error(self) -> None:
        error = internal_error("unexpected", detail="boom")
        assert error.status_code == 500
        assert error.error_code == "saena.internal.unexpected"
        assert error.retryable is False

    def test_internal_error_problem_detail_round_trips(self) -> None:
        error = internal_error("unexpected", detail="boom")
        problem = to_problem_detail(error, trace_id="a" * 32, instance="http://x/y")
        assert problem.status == 500
        assert problem.detail == "boom"


class TestProblemDetailRunIdField:
    def test_run_id_is_included_when_set_on_the_error(self) -> None:
        error = ServiceError(ErrorCategory.NOT_FOUND, "resource_missing", run_id="019f5769-abcd")
        problem = to_problem_detail(error, trace_id="b" * 32, instance="http://x/y")
        assert problem.run_id is not None
        assert problem.run_id.root == "019f5769-abcd"


class TestResolveTraceIdFallback:
    def test_resolve_trace_id_generates_when_state_has_no_trace_id(self) -> None:
        fake_request = SimpleNamespace(state=SimpleNamespace())
        trace_id = resolve_trace_id(fake_request)  # type: ignore[arg-type]
        assert isinstance(trace_id, str)
        assert len(trace_id) == 32


class TestRunStoreCrossTenantPutCollision:
    def test_put_rejects_same_run_id_under_a_different_tenant(self) -> None:
        store = RunStore()
        run = RuncontextLifecycle.model_validate(
            {
                "run_id": "shared-run-id",
                "tenant_id": "acme-corp",
                "state": "INTAKE",
                "base_commit": "a" * 40,
                "human_approval_required": True,
            }
        )
        store.put("acme-corp", run)

        colliding_run = RuncontextLifecycle.model_validate(
            {
                "run_id": "shared-run-id",
                "tenant_id": "other-corp",
                "state": "INTAKE",
                "base_commit": "b" * 40,
                "human_approval_required": True,
            }
        )
        with pytest.raises(RunTenantIsolationError):
            store.put("other-corp", colliding_run)


class TestRequireTenantRejectsSystemActorWithoutTenant:
    def test_creating_a_run_as_a_tenantless_system_actor_is_rejected(
        self, client: TestClient
    ) -> None:
        headers = actor_headers(actor_type="system", tenant_id=None, roles="proposer")
        response = client.post(
            "/v1/runs",
            json={"state": "INTAKE", "base_commit": "a" * 40, "human_approval_required": True},
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "saena.validation.tenant_id_required"


class TestBuildRequestActorInvalidValueError:
    def test_malformed_actor_id_raises_validation_error(self) -> None:
        # ActorId has max_length=128 -- an over-long actor_id fails the
        # generated model's own Field constraint, surfacing as a bare
        # ValueError from ActorContext.from_payload (not
        # ActorTenantRequiredError), exercising the second except clause in
        # build_request_actor.
        fake_request = SimpleNamespace(
            headers={
                "X-Saena-Actor-Id": "a" * 200,
                "X-Saena-Session-Id": "session-0001",
                "X-Saena-Actor-Type": "system",
            }
        )
        with pytest.raises(ServiceError) as exc_info:
            build_request_actor(fake_request)  # type: ignore[arg-type]
        assert exc_info.value.error_code == "saena.validation.invalid_actor_context"


class TestEmptyTenantHeaderTreatedAsAbsent:
    def test_whitespace_only_tenant_header_is_treated_as_no_tenant(self) -> None:
        # Exercises `build_request_actor`'s own empty-string-after-strip ->
        # None normalization directly, bypassing the tenant-reconciliation
        # middleware (which would 403 on a present-but-mismatched header
        # before this code ever runs in a full HTTP round trip -- see
        # `svc_forge_console.conftest.actor_headers`'s module for the
        # ordering this unit test sidesteps).
        fake_request = SimpleNamespace(
            headers={
                "X-Saena-Actor-Id": "actor-0001",
                "X-Saena-Session-Id": "session-0001",
                "X-Saena-Actor-Type": "system",
                "X-Saena-Tenant-Id": "   ",
            }
        )
        request_actor = build_request_actor(fake_request)  # type: ignore[arg-type]
        assert request_actor.actor.tenant_id is None
