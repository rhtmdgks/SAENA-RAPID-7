"""Request/response DTOs for the tenant-control HTTP API.

No duplicate DTOs for the generated `TenantContext`
(`saena_schemas.context.tenant_context_v1.TenantContext`) fields — every
response body that represents a tenant returns that model's own
`model_dump()` shape (via `saena_domain.identity.TenantContext.model`).
The two request models below exist ONLY because the generated `TenantContext`
model does not (and must not) match the request shape 1:1:

- `TenantCreateRequest` omits `namespace`/`status`/`created_at`/`updated_at`
  (server-computed, ADR-0014 Constraints:65 — accepting them as input would
  let a caller smuggle an inconsistent `namespace`, and status/timestamps are
  always fresh at creation).
- `TenantStatusUpdateRequest` is a single-field transition request, not a
  tenant representation at all.

Both use `extra="forbid"` (`model_config`) so a request that DOES include
`namespace` fails schema validation (pydantic `RequestValidationError`) at
the FastAPI layer — `app.py`'s `_validation_error_handler` detects that
specific "extra `namespace` field" shape and reshapes it into the
ADR-0015-shaped `NamespaceInputRejectedError` problem response (distinct
`error_code` from the generic validation category, task spec: "input
namespace REJECTED — computed only") rather than FastAPI's default 422 body.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Status transitions this service exposes on
#: `POST /v1/tenants/{tenant_id}/status` (ADR-0014 status enum minus the
#: unreachable-via-API `active` re-entry from `active` itself, which
#: `service.py`'s state machine rejects as a no-op transition).
StatusAction = Literal["suspend", "reactivate", "terminate"]


class TenantCreateRequest(BaseModel):
    """`POST /v1/tenants` request body.

    Mirrors `TenantContext`'s caller-supplied fields only —
    `namespace`/`status`/`created_at`/`updated_at` are server-computed (see
    module docstring) and therefore absent here; supplying any of them is a
    422 (unknown field, `extra="forbid"`) at the FastAPI layer.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1)
    isolation_profile: Literal["internal-k3s", "saas-shared"]
    policy_version: str
    engine_scope: list[str] = Field(min_length=1)
    retention_policy_ref: str = Field(min_length=1)


class TenantStatusUpdateRequest(BaseModel):
    """`POST /v1/tenants/{tenant_id}/status` request body."""

    model_config = ConfigDict(extra="forbid")

    action: StatusAction


class TenantStatusUpdateResponse(BaseModel):
    """`POST /v1/tenants/{tenant_id}/status` response body.

    Documents the status-change decision directly in the response (and via
    structured log, `service.py`) rather than an `AuditEvent`/domain event —
    see `service.py` module docstring "why no `tenant.policy.updated.v1`".
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    previous_status: str
    status: str
    action: StatusAction


class TenantRecordResponse(BaseModel):
    """`GET /v1/tenants/{tenant_id}/record` response body — gate-free admin
    status view (works for suspended/terminating tenants, unlike
    `GET /v1/tenants/{tenant_id}`)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    status: str
    raw_payload: dict[str, Any]
