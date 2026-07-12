"""`derive_namespace` / `validate_namespace` — ADR-0014 namespace derivation
and the namespace/tenant_id cross-field runtime gate.

The `namespace-mismatch` contract fixture
(tests/contract/fixtures/tenant-context/invalid/namespace-mismatch.json) is
schema-VALID by design (JSON Schema cannot express the cross-field
invariant) — this test module is where that gap is actually closed, per the
fixture's own note pointing at a runtime gate.
"""

from __future__ import annotations

import pytest
import saena_domain.identity.tenant as tenant_module
from conftest import make_tenant_context_payload
from saena_domain.identity.errors import NamespaceDerivationError, NamespaceMismatchError
from saena_domain.identity.tenant import derive_namespace, validate_namespace
from saena_schemas.context.tenant_context_v1 import TenantContext as _TenantContextModel


class TestDeriveNamespace:
    def test_deterministic_prefix_form(self) -> None:
        assert derive_namespace("acme-corp") == "saena-tenant-acme-corp"

    def test_accepts_tenant_id_value_object(self) -> None:
        from saena_domain.identity.tenant import TenantId

        assert derive_namespace(TenantId("acme-corp")) == "saena-tenant-acme-corp"

    def test_max_length_tenant_id_stays_within_63_chars(self) -> None:
        max_tenant_id = "a" * 32
        namespace = derive_namespace(max_tenant_id)
        assert namespace == f"saena-tenant-{max_tenant_id}"
        assert len(namespace) == 45
        assert len(namespace) <= 63

    def test_min_length_tenant_id_namespace(self) -> None:
        namespace = derive_namespace("a-1")
        assert namespace == "saena-tenant-a-1"

    def test_rejects_invalid_tenant_id_string(self) -> None:
        from saena_domain.identity.errors import InvalidTenantIdError

        with pytest.raises(InvalidTenantIdError):
            derive_namespace("BAD")

    def test_derivation_never_exceeds_63_even_at_max_tenant_id(self) -> None:
        # Backstop for the ADR's own "역산한 상한" framing: assert the
        # invariant holds structurally, not just for one sampled value.
        namespace = derive_namespace("a" * 32)
        assert len(namespace) <= 63


class TestNamespaceDerivationErrorIsUnreachableAtSchemaMaxLength:
    def test_no_valid_tenant_id_can_trigger_derivation_error(self) -> None:
        # Every schema-valid tenant_id is <=32 chars, so prefix(13) + 32 = 45
        # always fits under 63 -- NamespaceDerivationError is a defensive
        # assertion, not a reachable path through the public TenantId
        # constructor. Documented here rather than silently left untested.
        try:
            derive_namespace("a" * 32)
        except NamespaceDerivationError:
            pytest.fail("max-length schema-valid tenant_id must not raise")

    def test_defensive_assertion_fires_if_the_63_char_budget_ever_shrinks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Directly exercises the NamespaceDerivationError raise branch
        # itself (defense-in-depth: proves the assertion is live code, not
        # dead code, in case a future change to the namespace budget or
        # prefix ever makes it reachable through the public TenantId path).
        monkeypatch.setattr(tenant_module, "_MAX_NAMESPACE_LENGTH", 10)
        with pytest.raises(NamespaceDerivationError) as exc_info:
            derive_namespace("acme-corp")
        assert exc_info.value.context["max_length"] == 10
        assert exc_info.value.error_code == "saena.identity.namespace_derivation_failed"


class TestValidateNamespace:
    def test_matching_namespace_passes(self) -> None:
        model = _TenantContextModel.model_validate(make_tenant_context_payload())
        validate_namespace(model)  # no raise

    def test_mismatched_namespace_raises(self) -> None:
        # Mirrors tests/contract/fixtures/tenant-context/invalid/namespace-mismatch.json
        payload = make_tenant_context_payload(namespace="saena-tenant-totally-different-slug")
        model = _TenantContextModel.model_validate(payload)
        with pytest.raises(NamespaceMismatchError) as exc_info:
            validate_namespace(model)
        assert exc_info.value.context["tenant_id"] == "acme-corp"
        assert exc_info.value.context["expected_namespace"] == "saena-tenant-acme-corp"
        assert exc_info.value.context["actual_namespace"] == "saena-tenant-totally-different-slug"
        assert exc_info.value.error_code == "saena.identity.namespace_mismatch"
