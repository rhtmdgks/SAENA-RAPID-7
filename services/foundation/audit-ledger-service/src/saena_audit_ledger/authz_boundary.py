"""W2A authN/authZ boundary stub: `X-Saena-Roles` header -> RBAC roles.

Real authentication (verifying the caller IS who the roles claim) is a W3+
concern — see the module docstring below and README status update. What IS
real here, and never stubbed: the RBAC decision itself. Once roles are
extracted from the header, `saena_domain.authz.authorize` — the same
default-deny allow matrix used everywhere else in the domain layer — makes
the actual allow/deny call. A W3 authN layer replacing this header parse with
verified claims (mTLS client cert, JWT, etc.) only needs to change how
`roles_from_header` obtains its role set; `require_permission`'s enforcement
logic does not change.
"""

from __future__ import annotations

from fastapi import Request
from saena_domain.authz import Permission, Role, authorize

#: W2A stub transport for caller roles — comma-separated `Role` values.
#: Documented limitation: nothing here verifies the caller actually holds
#: these roles (no signature, no mTLS identity binding) — a real deployment
#: MUST replace this header with an authenticated identity source before
#: leaving W2A. See README "Implementation status" for the tracked gap.
ROLES_HEADER_NAME = "X-Saena-Roles"


def roles_from_header(request: Request) -> frozenset[Role]:
    """Parse `X-Saena-Roles` into a `frozenset[Role]`, ignoring unknown tokens.

    Missing header or empty value yields an empty role set (default-deny at
    every downstream `authorize()` call — never treated as "any role").
    Unknown/misspelled role tokens are silently dropped rather than raising:
    an unrecognized token can never grant a permission (it will never appear
    in `ALLOW_MATRIX`), so treating it as absent is equivalent to rejecting
    it, without turning a client typo into a 5xx.
    """
    raw = request.headers.get(ROLES_HEADER_NAME)
    if not raw:
        return frozenset()
    tokens = [tok.strip() for tok in raw.split(",") if tok.strip()]
    roles: set[Role] = set()
    for token in tokens:
        try:
            roles.add(Role(token))
        except ValueError:
            continue
    return frozenset(roles)


def has_permission(request: Request, permission: Permission) -> bool:
    """True iff the caller's `X-Saena-Roles` grant `permission` (default-deny)."""
    return authorize(roles_from_header(request), permission)
