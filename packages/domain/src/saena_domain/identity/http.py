"""Synchronous HTTP tenant-reconciliation primitive (ADR-0014).

ADR-0014's "동기 HTTP" propagation row: the `X-Saena-Tenant-Id` request
header must match the pod's `SAENA_TENANT_ID` env var; a mismatch is
rejected with 403 + an audit event (ADR-0014 Constraints:64 — "mismatch를
조용히 무시하거나 200으로 처리하는 코드 경로 금지"). This module only supplies the
comparison primitive and the header/env name constants; mapping
`TenantMismatchError` to an actual HTTP 403 response and publishing the
audit event are services-layer concerns (framework + audit-ledger
dependencies neither of which belong in `saena_domain`).
"""

from __future__ import annotations

from typing import Final

from saena_domain.identity.errors import TenantMismatchError

#: HTTP request header carrying the caller's claimed tenant (ADR-0014).
TENANT_HEADER_NAME: Final[str] = "X-Saena-Tenant-Id"

#: Pod environment variable carrying the tenant this pod is scoped to
#: (ADR-0014, tenancy-model.md internal-k3s env-var pattern).
TENANT_ENV_VAR_NAME: Final[str] = "SAENA_TENANT_ID"


def reconcile_tenant(header_value: str | None, env_value: str | None) -> str:
    """Reconcile the `X-Saena-Tenant-Id` header against the pod's
    `SAENA_TENANT_ID` env var.

    Returns the reconciled `tenant_id` string on success (header and env
    agree, and neither is missing/empty). Raises `TenantMismatchError`
    otherwise — including when either value is `None`/empty, since a missing
    value on either side is exactly the "silently proceed" case ADR-0014
    forbids. The raised exception's `.context` carries which side held which
    value, structured for the services layer to fold directly into an audit
    event payload (never logged/returned as free text — ADR-0014
    Constraints:64 "어느 값과 불일치했는지 audit payload에 기록").
    """
    if not header_value or not env_value:
        raise TenantMismatchError(
            "tenant reconciliation requires both header and env values to be present and non-empty",
            context={
                "header_name": TENANT_HEADER_NAME,
                "env_var_name": TENANT_ENV_VAR_NAME,
                "header_value": header_value,
                "env_value": env_value,
            },
        )
    if header_value != env_value:
        raise TenantMismatchError(
            f"X-Saena-Tenant-Id header {header_value!r} does not match "
            f"SAENA_TENANT_ID env {env_value!r}",
            context={
                "header_name": TENANT_HEADER_NAME,
                "env_var_name": TENANT_ENV_VAR_NAME,
                "header_value": header_value,
                "env_value": env_value,
            },
        )
    return header_value
