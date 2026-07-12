"""Route-level RBAC enforcement dependency, default-deny (`saena_domain.authz`).

`require_permission(permission)` returns a FastAPI dependency that:
  1. Resolves the caller's `RequestActor` (`saena_forge_console.authn.
     build_request_actor` — itself a FastAPI dependency, composed here rather
     than re-parsed).
  2. Calls `saena_domain.authz.authorize(roles, permission)`.
  3. Raises a `policy_denied`-category `ServiceError` (HTTP 403) if
     `authorize` returns `False` — which includes the empty-role-set case
     (no `X-Saena-Roles` header at all), since `authorize()` has no
     implicit-allow path (`saena_domain.authz.rbac` module docstring).

This is the ONLY place route code checks permissions — no route handler in
this service calls `authorize()` directly, so the default-deny posture is
structural (every route that needs a permission declares it via this one
dependency factory) rather than something each handler could individually
forget.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from saena_domain.authz import Permission, authorize

from saena_forge_console.authn import RequestActor, build_request_actor
from saena_forge_console.errors import policy_denied_error


def _get_request_actor(request: Request) -> RequestActor:
    return build_request_actor(request)


def require_permission(permission: Permission) -> Callable[[RequestActor], RequestActor]:
    """Build a FastAPI dependency CALLABLE enforcing `permission`
    (default-deny). Returns the bare callable, not a `fastapi.Depends(...)`
    wrapper — callers wrap it themselves (`Depends(require_permission(...))`
    at the route parameter default), matching how every other dependency in
    this service is declared; wrapping it here too would double-wrap
    (`Depends(Depends(...))`), which FastAPI's signature introspection
    cannot resolve.
    """

    def _dependency(
        request_actor: RequestActor = Depends(_get_request_actor),  # noqa: B008
    ) -> RequestActor:
        if not authorize(request_actor.roles, permission):
            raise policy_denied_error(
                "permission_denied",
                detail=(
                    f"actor lacks permission {permission.value!r} "
                    f"(roles={sorted(r.value for r in request_actor.roles)!r})"
                ),
                tenant_id=request_actor.actor.tenant_id,
            )
        return request_actor

    return _dependency


__all__ = ["require_permission"]
