"""In-memory run-metadata store, keyed `(tenant_id, run_id)` — run ownership
is THIS service per `docs/architecture/service-catalog.md` ("forge-console-api
owns run metadata"). Deliberately local to this service, not a
`saena_domain.persistence` port: run metadata is forge-console-api's own
aggregate, not a shared cross-service contract store like
`TenantRepository`/`PlanRepository` (those are owned by tenant-control /
plan-contract respectively, `saena_domain.persistence.ports`).

Stores the run as a `saena_schemas.context.run_context_lifecycle_v1.
RuncontextLifecycle` generated pydantic model (no hand DTO) — the model's
`extra="allow"` config (codegen "open" contract) means callers may attach
additional, not-yet-schema'd fields at construction time without this store
rejecting them.

Tenant isolation mirrors `saena_domain.persistence.memory`'s established
pattern (this patch unit's own exclusive-write scope does not include that
package, so the shape is intentionally duplicated here rather than imported
— this is a service-local store, not a `saena_domain.persistence` adapter):
a caller supplying a `tenant_id` that does not own the requested `run_id`
gets `RunTenantIsolationError`, never a bare `RunNotFoundError` — "exists,
but not yours" is a distinct, security-relevant outcome from "never
existed".
"""

from __future__ import annotations

import threading

from saena_schemas.context.run_context_lifecycle_v1 import RuncontextLifecycle


class RunStoreError(Exception):
    """Base class for `RunStore` errors."""

    error_code: str = "saena.forge_console.run_store_error"


class RunNotFoundError(RunStoreError):
    error_code = "saena.not_found.resource_missing"


class RunTenantIsolationError(RunStoreError):
    error_code = "saena.policy_denied.tenant_isolation_violation"


class RunStore:
    """Pure in-memory reference store, process-local (no persistence across
    restarts — acceptable for W2A per this service's README/status note;
    a real datastore-backed adapter is out of this patch unit's scope, same
    "SQL adapters land later" posture `saena_domain.persistence.ports`
    documents for its own ports).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # run_id -> (tenant_id, RuncontextLifecycle)
        self._runs: dict[str, tuple[str, RuncontextLifecycle]] = {}

    def put(self, tenant_id: str, run: RuncontextLifecycle) -> RuncontextLifecycle:
        run_id = run.run_id.root
        with self._lock:
            existing = self._runs.get(run_id)
            if existing is not None and existing[0] != tenant_id:
                raise RunTenantIsolationError(f"run_id {run_id!r} belongs to a different tenant")
            self._runs[run_id] = (tenant_id, run)
        return run

    def get(self, tenant_id: str, run_id: str) -> RuncontextLifecycle:
        with self._lock:
            entry = self._runs.get(run_id)
        if entry is None:
            raise RunNotFoundError(f"no run stored for run_id {run_id!r}")
        owner_tenant_id, run = entry
        if owner_tenant_id != tenant_id:
            raise RunTenantIsolationError(f"run_id {run_id!r} belongs to a different tenant")
        return run


__all__ = ["RunNotFoundError", "RunStore", "RunStoreError", "RunTenantIsolationError"]
