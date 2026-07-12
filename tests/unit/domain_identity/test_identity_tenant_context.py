"""`TenantContext` runtime wrapper — status gate, engine_scope guard,
tolerant-read status handling.
"""

from __future__ import annotations

import pytest
import saena_domain.identity.tenant as tenant_module
from conftest import make_tenant_context_payload
from saena_domain.identity.errors import (
    EngineScopeError,
    NamespaceMismatchError,
    TenantSuspendedError,
    TenantTerminatingError,
)
from saena_domain.identity.tenant import TenantContext


class TestConstruction:
    def test_active_tenant_constructs_successfully(self, tenant_context_payload: dict) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        assert ctx.tenant_id.value == "acme-corp"
        assert ctx.status == "active"
        assert ctx.namespace == "saena-tenant-acme-corp"
        assert ctx.isolation_profile == "internal-k3s"
        assert ctx.engine_scope == ("chatgpt-search",)

    def test_construction_validates_namespace(self) -> None:
        payload = make_tenant_context_payload(namespace="saena-tenant-wrong-slug")
        with pytest.raises(NamespaceMismatchError):
            TenantContext.from_payload(payload)


class TestStatusGate:
    def test_suspended_tenant_denied(self) -> None:
        payload = make_tenant_context_payload(status="suspended")
        with pytest.raises(TenantSuspendedError) as exc_info:
            TenantContext.from_payload(payload)
        assert exc_info.value.context["status"] == "suspended"
        assert exc_info.value.error_code == "saena.identity.tenant_suspended"

    def test_terminating_tenant_denied(self) -> None:
        payload = make_tenant_context_payload(status="terminating")
        with pytest.raises(TenantTerminatingError) as exc_info:
            TenantContext.from_payload(payload)
        assert exc_info.value.context["status"] == "terminating"

    def test_terminating_is_a_suspended_subclass(self) -> None:
        # Callers guarding the general "not usable" case can catch the
        # parent TenantSuspendedError.
        assert issubclass(TenantTerminatingError, TenantSuspendedError)
        payload = make_tenant_context_payload(status="terminating")
        with pytest.raises(TenantSuspendedError):
            TenantContext.from_payload(payload)

    def test_active_status_not_denied(self) -> None:
        payload = make_tenant_context_payload(status="active")
        TenantContext.from_payload(payload)  # no raise


class TestEngineScopeGuard:
    def test_require_engine_accepts_scoped_engine(self, tenant_context_payload: dict) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        ctx.require_engine("chatgpt-search")  # no raise

    def test_require_engine_rejects_google(self, tenant_context_payload: dict) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        with pytest.raises(EngineScopeError) as exc_info:
            ctx.require_engine("google-ai-overviews")
        assert exc_info.value.context["engine_id"] == "google-ai-overviews"
        assert exc_info.value.error_code == "saena.identity.engine_scope_denied"

    def test_require_engine_rejects_gemini(self, tenant_context_payload: dict) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        with pytest.raises(EngineScopeError):
            ctx.require_engine("gemini")

    def test_require_engine_rejects_empty_string(self, tenant_context_payload: dict) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        with pytest.raises(EngineScopeError):
            ctx.require_engine("")

    def test_require_engine_rejects_engine_outside_this_tenants_own_scope(
        self, tenant_context_payload: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Today every schema-valid TenantContext has engine_scope ==
        # ["chatgpt-search"] (engine_id is a closed single-value enum, so no
        # schema-valid payload can ever have a NARROWER scope than the v1
        # allow-list). This test exercises the second guard clause directly
        # (globally-allowed engine, but outside *this* tenant's own
        # engine_scope) by widening the v1 allow-list for the duration of
        # the test -- forward-looking coverage for a future multi-engine
        # widening, not a reachable case through today's schema.
        monkeypatch.setattr(
            tenant_module, "_ALLOWED_ENGINE_SCOPE", frozenset({"chatgpt-search", "future-engine"})
        )
        ctx = TenantContext.from_payload(tenant_context_payload)
        with pytest.raises(EngineScopeError) as exc_info:
            ctx.require_engine("future-engine")
        assert exc_info.value.context["engine_scope"] == ["chatgpt-search"]
        assert exc_info.value.error_code == "saena.identity.engine_scope_denied"


class TestReprAndEquality:
    def test_repr_contains_tenant_id_and_status(self, tenant_context_payload: dict) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        text = repr(ctx)
        assert "acme-corp" in text
        assert "active" in text

    def test_equality_by_underlying_model(self, tenant_context_payload: dict) -> None:
        a = TenantContext.from_payload(tenant_context_payload)
        b = TenantContext.from_payload(dict(tenant_context_payload))
        assert a == b

    def test_hash_stable_by_tenant_id(self, tenant_context_payload: dict) -> None:
        a = TenantContext.from_payload(tenant_context_payload)
        b = TenantContext.from_payload(dict(tenant_context_payload))
        assert hash(a) == hash(b)

    def test_equality_against_non_tenant_context_is_not_implemented(
        self, tenant_context_payload: dict
    ) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        assert ctx.__eq__("not-a-tenant-context") is NotImplemented
        assert ctx != "not-a-tenant-context"

    def test_model_property_exposes_generated_pydantic_model(
        self, tenant_context_payload: dict
    ) -> None:
        ctx = TenantContext.from_payload(tenant_context_payload)
        assert ctx.model.tenant_id.root == "acme-corp"


# --- Tolerant-read worked example -------------------------------------------
#
# Mirrors tests/contract/fixtures/tenant-context/invalid/
# unknown-status-tolerant-read.json's obligation: a *consumer*-side status
# resolver must degrade an unrecognized future `status` value safely
# (fallback branch, no raise) rather than crash, modeling the old-consumer/
# new-producer overlap window across a future minor-version enum widening.
# This is deliberately a plain string-based resolver (not routed through the
# generated Status StrEnum, which is a *closed* enum and would itself raise
# on an unrecognized value at model-validation time) to demonstrate the
# obligation at the boundary where raw wire data first arrives.


def resolve_tenant_status(raw_status: str) -> str:
    """Consumer-side tolerant-read resolver: known statuses map through,
    anything else degrades to `"unknown"` rather than raising."""
    known = {"active", "suspended", "terminating"}
    return raw_status if raw_status in known else "unknown"


class TestTolerantReadStatus:
    @pytest.mark.parametrize("status", ["active", "suspended", "terminating"])
    def test_known_status_passes_through(self, status: str) -> None:
        assert resolve_tenant_status(status) == status

    def test_unknown_future_status_degrades_to_unknown_without_raising(self) -> None:
        # "archived" — the exact value from the unknown-status-tolerant-read
        # fixture.
        assert resolve_tenant_status("archived") == "unknown"

    def test_generated_model_itself_rejects_unknown_status_pre_rollout(self) -> None:
        # Confirms the OTHER half of the story: today, before any minor-
        # version widening, the closed Status enum on the generated model
        # still rejects "archived" at construction time (ValidationError),
        # which is why the tolerant-read obligation lives at the consumer
        # boundary (resolve_tenant_status) rather than inside the DTO.
        import pydantic

        payload = make_tenant_context_payload(status="archived")
        with pytest.raises(pydantic.ValidationError):
            TenantContext.from_payload(payload)
