"""saena_forge_console — the v1 sole edge API (ADR-0007 D-4).

`create_app()` (`saena_forge_console.app`) builds the FastAPI ASGI app: AuthN
header stub -> RBAC default-deny (`saena_domain.authz`) -> tenant
reconciliation (ADR-0014) -> run-metadata routes (owned by this service per
`docs/architecture/service-catalog.md`) -> lineage passthrough edge gate.

See `services/platform/forge-console-api/README.md` for status and scope.
"""

from __future__ import annotations

from saena_forge_console.app import create_app

__all__ = ["create_app"]

__version__ = "0.1.0"
