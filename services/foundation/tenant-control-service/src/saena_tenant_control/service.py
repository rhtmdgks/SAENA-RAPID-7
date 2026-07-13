"""Tenant-control business logic — create/get/get_record/update_status.

Wraps `saena_domain.identity`/`saena_domain.persistence` ports; performs no
I/O of its own beyond what the injected `TenantRepository`/`OutboxPort` do.

**Why no `tenant.policy.updated.v1` event**: the tenant-control-service
README lists `tenant.policy.updated.v1` as a **PROPOSED** (unconfirmed)
published event — it does not appear in the CONFIRMED v1 AsyncAPI catalog
(`packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`, checked at
patch-unit-write time: 11 tenant + 1 aggregate channel, zero
`tenant.policy.updated.v1`). `EnvelopeFactory.build_tenant_envelope` would
reject any attempt to build an envelope for an undeclared `event_type` with
`TopicMismatchError` — publishing it here would either require bypassing
that check (never acceptable) or asserting a not-yet-approved topic into the
production catalog from a services-layer patch unit (out of this unit's
exclusive write paths; `packages/contracts` is a single-owner path per
CLAUDE.md §7). Status-change decisions are instead: (a) returned directly in
the `POST /v1/tenants/{tenant_id}/status` response body
(`TenantStatusUpdateResponse`), and (b) recorded via a structured log line
(`saena_observability.get_logger`) carrying `error_code`-shaped
`saena.*`-namespaced attributes for correlation — no attempt is made to
fabricate an ad hoc "audit" write to `saena_domain.persistence.OutboxPort`
for a topic that does not exist; `record()` would itself reject a
non-catalog `event_type` at the envelope-shape level once fed through
`EnvelopeFactory`, and hand-building a raw dict that merely *looks* like a
valid envelope without going through `EnvelopeFactory` would defeat the
single-authority-construction point that factory exists to be.
"""

from __future__ import annotations

import datetime as _dt
from typing import Final

from saena_domain.identity import (
    TenantContext,
    TenantId,
    derive_namespace,
)
from saena_domain.persistence import NotFoundError as _DomainNotFoundError
from saena_domain.persistence import OutboxPort, TenantRecord, TenantRepository
from saena_observability import get_logger

from saena_tenant_control.errors import (
    EngineScopeViolationProblem,
    InvalidStatusTransitionProblem,
    TenantAlreadyExistsProblem,
    TenantNotFoundProblem,
)
from saena_tenant_control.schemas import StatusAction, TenantCreateRequest

_logger = get_logger("saena_tenant_control.service")

#: v1 closed engine allow-list (CLAUDE.md Engine scope; ADR-0013:58) —
#: mirrors `saena_domain.identity.tenant._ALLOWED_ENGINE_SCOPE`, duplicated
#: here (not imported — that name is module-private) for the request-level
#: guard that must fire before a `TenantContext` is even constructed, so an
#: out-of-scope `engine_scope` gets this service's own
#: `EngineScopeViolationProblem` (403, `policy_denied` category) rather than
#: whatever exception shape a downstream construction failure would raise.
_ALLOWED_ENGINE_SCOPE: Final[frozenset[str]] = frozenset({"chatgpt-search"})

#: ADR-0014 status enum state machine for `POST .../status`. `active` is
#: reachable only via `reactivate` (from `suspended`) — there is no path
#: back out of `terminating` (terminal state, matches the enum's own
#: lifecycle framing: "terminating" is not "terminated" but this service
#: exposes no further transition out of it).
_ALLOWED_TRANSITIONS: Final[dict[str, dict[StatusAction, str]]] = {
    "active": {"suspend": "suspended", "terminate": "terminating"},
    "suspended": {"reactivate": "active", "terminate": "terminating"},
    "terminating": {},
}


def _utc_now() -> str:
    return _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_tenant(repo: TenantRepository, request: TenantCreateRequest) -> TenantContext:
    """Create a new tenant. `namespace` is always server-derived from
    `tenant_id` (ADR-0014 Constraints:65) — `TenantCreateRequest` (`schemas.py`)
    structurally has no `namespace` field and sets `extra="forbid"`, so a
    request body that supplies `namespace` is rejected as a schema violation
    (`RequestValidationError` -> `NamespaceInputRejectedError`-shaped 400
    problem, `errors.py`/`app.py`) BEFORE this function is ever called — this
    is the single enforcement point, there is no second in-function check to
    bypass, matching the "computed field, never an independent input"
    wording of ADR-0014 Constraints:65 at the type level rather than a
    runtime re-check.
    """
    for engine_id in request.engine_scope:
        if engine_id not in _ALLOWED_ENGINE_SCOPE:
            raise EngineScopeViolationProblem(
                f"engine {engine_id!r} is outside the v1 engine scope "
                f"{sorted(_ALLOWED_ENGINE_SCOPE)!r}",
                context={"engine_id": engine_id, "tenant_id": request.tenant_id},
            )

    tenant_id = TenantId(request.tenant_id)

    try:
        repo.get_record(tenant_id)
    except _DomainNotFoundError:
        pass
    else:
        raise TenantAlreadyExistsProblem(
            f"tenant_id {request.tenant_id!r} already exists",
            context={"tenant_id": request.tenant_id},
        )

    namespace = derive_namespace(tenant_id)
    now = _utc_now()
    payload: dict[str, object] = {
        "tenant_id": request.tenant_id,
        "display_name": request.display_name,
        "isolation_profile": request.isolation_profile,
        "namespace": namespace,
        "policy_version": request.policy_version,
        "engine_scope": list(request.engine_scope),
        "status": "active",
        "retention_policy_ref": request.retention_policy_ref,
        "created_at": now,
        "updated_at": now,
    }
    # `TenantContext.__init__` (`saena_domain.identity.tenant`) does not
    # itself call `require_engine` — that guard is a separate opt-in method
    # for callers that need to check a specific engine_id at request time,
    # not a construction-time invariant — so `from_payload` cannot raise
    # `EngineScopeError` here; the pre-check loop above is this function's
    # sole engine-scope enforcement point (already covers every entry in
    # `payload["engine_scope"]` before construction is attempted).
    context = TenantContext.from_payload(payload)

    repo.put(tenant_id, context)
    return context


def get_tenant(repo: TenantRepository, tenant_id_value: str) -> TenantContext:
    """Gated read — raises `TenantSuspendedError`/`TenantTerminatingError`
    (propagated from `saena_domain.identity`, mapped to a 403 problem by
    `errors.to_problem_detail`) for a non-active tenant."""
    tenant_id = TenantId(tenant_id_value)
    try:
        return repo.get(tenant_id)
    except _DomainNotFoundError as exc:
        raise TenantNotFoundProblem(str(exc), context=exc.context) from exc


def get_tenant_record(repo: TenantRepository, tenant_id_value: str) -> TenantRecord:
    """Gate-free admin/status view — works for suspended/terminating tenants."""
    tenant_id = TenantId(tenant_id_value)
    try:
        return repo.get_record(tenant_id)
    except _DomainNotFoundError as exc:
        raise TenantNotFoundProblem(str(exc), context=exc.context) from exc


def update_tenant_status(
    repo: TenantRepository,
    outbox: OutboxPort,  # noqa: ARG001 - reserved for a future confirmed topic; see module docstring
    tenant_id_value: str,
    action: StatusAction,
) -> tuple[str, str]:
    """Apply a `suspend`/`reactivate`/`terminate` transition.

    Returns `(previous_status, new_status)`. Raises
    `InvalidStatusTransitionProblem` (409) if `action` is not legal from the
    tenant's current status per `_ALLOWED_TRANSITIONS`. `outbox` is accepted
    (dependency-injected alongside `repo` for callers that construct both
    together) but unused — see module docstring "why no
    `tenant.policy.updated.v1` event" for why this method does not write to
    it.
    """
    tenant_id = TenantId(tenant_id_value)
    record = get_tenant_record(repo, tenant_id_value)
    current_status = record.status
    transitions = _ALLOWED_TRANSITIONS.get(current_status, {})
    new_status = transitions.get(action)
    if new_status is None:
        raise InvalidStatusTransitionProblem(
            f"transition {action!r} is not legal from status {current_status!r}",
            context={
                "tenant_id": tenant_id_value,
                "current_status": current_status,
                "requested_action": action,
            },
        )

    repo.update_status(tenant_id, new_status)

    _logger.info(
        "tenant status transition applied",
        extra={
            "saena_attributes": {
                "saena.tenant_id": tenant_id_value,
                "saena.previous_status": current_status,
                "saena.new_status": new_status,
                "saena.status_action": action,
            }
        },
    )
    return current_status, new_status
