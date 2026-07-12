"""AuthN stub: header-derived `ActorContext` construction (W1-era identity
provider stand-in).

Real identity provider (OIDC/JWT verification, session issuance) is W3+
scope (`docs/architecture/implementation-waves.md`) — this module does not
verify a signature or call an external IdP. What IS real now: the
*construction and validation* of `saena_domain.identity.ActorContext` from
request headers, including the human-actor-requires-tenant_id conditional
(Security MUST-FIX 2 / `ActorTenantRequiredError`, enforced by the domain
layer, not re-implemented here) and the RBAC role set this service uses for
`authorize()` (`X-Saena-Roles`, comma-separated `saena_domain.authz.Role`
values).

Headers consumed:
    X-Saena-Actor-Id      required, non-empty.
    X-Saena-Session-Id    required, non-empty.
    X-Saena-Actor-Type    optional, `human` (default) | `system`.
    X-Saena-Tenant-Id     required when `X-Saena-Actor-Type: human` (or the
                          default), forwarded into `ActorContext.tenant_id` —
                          the same header ADR-0014's tenant-reconciliation
                          middleware (`saena_forge_console.tenant_reconcile`)
                          separately checks against `SAENA_TENANT_ID`. A
                          `system` actor may omit it.
    X-Saena-Roles         optional, comma-separated role names
                          (`saena_domain.authz.Role` values); unknown role
                          tokens are rejected (fail-closed, not silently
                          dropped) so a typo'd role can never silently
                          collapse to "no roles" and pass through
                          default-deny by accident-shaped luck.

Missing/empty `X-Saena-Actor-Id` or `X-Saena-Session-Id` raises `auth`
category (`saena.auth.actor_id_required` / `saena.auth.session_id_required`)
— this is the "no anonymous caller" gate; `X-Saena-Roles` absent/empty is
NOT an auth error, it resolves to an empty role set, which then fails every
`authorize()` check downstream (default-deny, `saena_domain.authz`) — i.e.
missing roles is a `policy_denied`-category failure at the RBAC dependency,
not an `auth`-category failure here.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from saena_domain.authz import Role
from saena_domain.identity import ActorContext, ActorTenantRequiredError

from saena_forge_console.errors import ServiceError, auth_error, validation_error

ACTOR_ID_HEADER = "X-Saena-Actor-Id"
SESSION_ID_HEADER = "X-Saena-Session-Id"
ACTOR_TYPE_HEADER = "X-Saena-Actor-Type"
ROLES_HEADER = "X-Saena-Roles"
TENANT_HEADER = "X-Saena-Tenant-Id"

_DEFAULT_ACTOR_TYPE = "human"


@dataclass(frozen=True, slots=True)
class RequestActor:
    """The two auth-adjacent facts a route needs about the caller: their
    validated `ActorContext` and the RBAC role set parsed from
    `X-Saena-Roles`. Kept as one bundle so a single FastAPI dependency can
    hand both to a route without a second header re-parse.
    """

    actor: ActorContext
    roles: frozenset[Role]


def _require_header(request: Request, name: str, *, reason: str) -> str:
    value = request.headers.get(name)
    if value is None or value.strip() == "":
        raise auth_error(reason, detail=f"missing required header {name!r}")
    return value


def _parse_roles(raw: str | None) -> frozenset[Role]:
    if raw is None or raw.strip() == "":
        return frozenset()
    tokens = [token.strip() for token in raw.split(",") if token.strip() != ""]
    roles: set[Role] = set()
    for token in tokens:
        try:
            roles.add(Role(token))
        except ValueError as exc:
            raise validation_error(
                "unknown_role", detail=f"unrecognized role {token!r} in {ROLES_HEADER}"
            ) from exc
    return frozenset(roles)


def build_request_actor(request: Request) -> RequestActor:
    """Construct a `RequestActor` from request headers.

    Raises `ServiceError` (auth/validation category) on malformed input;
    raises the propagated `ActorTenantRequiredError` (wrapped as a
    `validation` `ServiceError`) when a human actor is missing `tenant_id` —
    the exact contract-level conditional Security MUST-FIX 2 requires
    (`ActorContext.__init__`, `saena_domain.identity.actor`).
    """
    actor_id = _require_header(request, ACTOR_ID_HEADER, reason="actor_id_required")
    session_id = _require_header(request, SESSION_ID_HEADER, reason="session_id_required")
    actor_type = request.headers.get(ACTOR_TYPE_HEADER, _DEFAULT_ACTOR_TYPE).strip()
    if actor_type not in ("human", "system"):
        raise validation_error(
            "invalid_actor_type",
            detail=f"{ACTOR_TYPE_HEADER} must be 'human' or 'system', got {actor_type!r}",
        )
    tenant_id = request.headers.get(TENANT_HEADER)
    if tenant_id is not None and tenant_id.strip() == "":
        tenant_id = None

    payload: dict[str, object] = {
        "actor_id": actor_id,
        "actor_type": actor_type,
        "session_id": session_id,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id

    try:
        actor = ActorContext.from_payload(payload)
    except ActorTenantRequiredError as exc:
        raise validation_error(
            "actor_tenant_required",
            detail="human actor requires X-Saena-Tenant-Id (actor-context.schema.json "
            "allOf/if/then, Security MUST-FIX 2)",
        ) from exc
    except ValueError as exc:
        raise validation_error("invalid_actor_context", detail=str(exc)) from exc

    roles = _parse_roles(request.headers.get(ROLES_HEADER))
    return RequestActor(actor=actor, roles=roles)


__all__ = [
    "ACTOR_ID_HEADER",
    "ACTOR_TYPE_HEADER",
    "ROLES_HEADER",
    "SESSION_ID_HEADER",
    "TENANT_HEADER",
    "RequestActor",
    "ServiceError",
    "build_request_actor",
]
