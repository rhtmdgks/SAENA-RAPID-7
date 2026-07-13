"""`reconcile_tenant` — ADR-0014 synchronous HTTP tenant-propagation
primitive: `X-Saena-Tenant-Id` header vs `SAENA_TENANT_ID` env var.
"""

from __future__ import annotations

import pytest
from saena_domain.identity.errors import TenantMismatchError
from saena_domain.identity.http import (
    TENANT_ENV_VAR_NAME,
    TENANT_HEADER_NAME,
    reconcile_tenant,
)


class TestConstants:
    def test_header_name(self) -> None:
        assert TENANT_HEADER_NAME == "X-Saena-Tenant-Id"

    def test_env_var_name(self) -> None:
        assert TENANT_ENV_VAR_NAME == "SAENA_TENANT_ID"


class TestReconcileTenantSuccess:
    def test_matching_values_return_the_tenant_id(self) -> None:
        assert reconcile_tenant("acme-corp", "acme-corp") == "acme-corp"


class TestReconcileTenantMismatch:
    def test_differing_values_raise(self) -> None:
        with pytest.raises(TenantMismatchError) as exc_info:
            reconcile_tenant("acme-corp", "other-corp")
        assert exc_info.value.context["header_value"] == "acme-corp"
        assert exc_info.value.context["env_value"] == "other-corp"
        assert exc_info.value.error_code == "saena.identity.tenant_mismatch"

    def test_error_context_carries_header_and_env_names(self) -> None:
        with pytest.raises(TenantMismatchError) as exc_info:
            reconcile_tenant("acme-corp", "other-corp")
        assert exc_info.value.context["header_name"] == "X-Saena-Tenant-Id"
        assert exc_info.value.context["env_var_name"] == "SAENA_TENANT_ID"

    def test_never_returns_silently_on_mismatch(self) -> None:
        # ADR-0014 Constraints:64 -- mismatch must never be silently
        # ignored/200'd. Asserting the function always raises (never
        # returns) on any differing pair is the direct encoding of that
        # constraint.
        with pytest.raises(TenantMismatchError):
            reconcile_tenant("a", "b")

    def test_case_sensitive_comparison(self) -> None:
        # SHOULD-FIX 2 (critic, w2-01 review): reconciliation must be
        # case-SENSITIVE -- tenant_id itself is lowercase-only by ADR-0014's
        # own pattern, so a header/env pair differing only by case is not a
        # "same tenant, different casing" situation, it is a genuine
        # mismatch (and potentially a spoofing attempt) that must raise, not
        # be silently normalized/accepted.
        with pytest.raises(TenantMismatchError) as exc_info:
            reconcile_tenant("TENANT-A", "tenant-a")
        assert exc_info.value.context["header_value"] == "TENANT-A"
        assert exc_info.value.context["env_value"] == "tenant-a"


class TestReconcileTenantMissingValues:
    def test_missing_header_raises(self) -> None:
        with pytest.raises(TenantMismatchError) as exc_info:
            reconcile_tenant(None, "acme-corp")
        assert exc_info.value.context["header_value"] is None

    def test_missing_env_raises(self) -> None:
        with pytest.raises(TenantMismatchError) as exc_info:
            reconcile_tenant("acme-corp", None)
        assert exc_info.value.context["env_value"] is None

    def test_both_missing_raises(self) -> None:
        with pytest.raises(TenantMismatchError):
            reconcile_tenant(None, None)

    def test_empty_string_header_raises(self) -> None:
        with pytest.raises(TenantMismatchError):
            reconcile_tenant("", "acme-corp")

    def test_empty_string_env_raises(self) -> None:
        with pytest.raises(TenantMismatchError):
            reconcile_tenant("acme-corp", "")
