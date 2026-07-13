"""`saena_domain.identity.errors` base class — structured `.context` and
`to_dict()` used by audit/observability sinks.
"""

from __future__ import annotations

from saena_domain.identity.errors import IdentityError, InvalidTenantIdError


class TestIdentityErrorBase:
    def test_default_context_is_empty_dict(self) -> None:
        err = IdentityError("boom")
        assert err.context == {}

    def test_context_is_copied_not_aliased(self) -> None:
        source = {"tenant_id": "acme-corp"}
        err = IdentityError("boom", context=source)
        source["tenant_id"] = "mutated"
        assert err.context["tenant_id"] == "acme-corp"

    def test_to_dict_includes_error_code_message_and_context(self) -> None:
        err = IdentityError("boom", context={"tenant_id": "acme-corp"})
        result = err.to_dict()
        assert result == {
            "error_code": "saena.identity.error",
            "message": "boom",
            "tenant_id": "acme-corp",
        }

    def test_subclass_to_dict_uses_subclass_error_code(self) -> None:
        err = InvalidTenantIdError("bad tenant", context={"tenant_id": "BAD"})
        result = err.to_dict()
        assert result["error_code"] == "saena.identity.invalid_tenant_id"
        assert result["tenant_id"] == "BAD"
