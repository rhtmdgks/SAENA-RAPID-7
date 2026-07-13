"""`InMemorySiteInventoryStore` — tenant-scoped, in-memory observation store.

Mirrors `saena_artifact_registry.blobstore.InMemoryBlobStore`'s tenant-gate
discipline exactly: `get`/`put` both take an explicit `tenant_id` argument
which MUST match the stored/storing `SiteInventoryObservation.job_context.
tenant_id`, and a mismatch on EITHER path raises `CrossTenantObservationError`
rather than a bare "not found" that would let a caller distinguish "wrong
tenant" from "never existed". This is a reference in-memory adapter for this
unit's own tests only — a real persistence adapter (SQL, following
`saena_domain.persistence`'s port shape) is out of this patch unit's scope.
"""

from __future__ import annotations

import threading

from saena_site_discovery.errors import CrossTenantObservationError, SiteInventoryNotFoundError
from saena_site_discovery.inventory import SiteInventoryObservation


class InMemorySiteInventoryStore:
    """Pure-Python, tenant-scoped `SiteInventoryObservation` store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, SiteInventoryObservation]] = {}

    def put(
        self, tenant_id: str, site_id: str, observation: SiteInventoryObservation
    ) -> SiteInventoryObservation:
        """Store `observation` under `(tenant_id, site_id)`.

        Raises `CrossTenantObservationError` if `observation.job_context.
        tenant_id != tenant_id` — a caller cannot store an observation
        under a tenant it was not actually captured for.
        """
        if observation.job_context.tenant_id != tenant_id:
            raise CrossTenantObservationError(
                "observation.job_context.tenant_id does not match the storing tenant_id",
                context={"requested_tenant_id": tenant_id},
            )
        with self._lock:
            self._store.setdefault(tenant_id, {})[site_id] = observation
        return observation

    def get(self, tenant_id: str, site_id: str) -> SiteInventoryObservation:
        """Return the stored observation for `(tenant_id, site_id)`.

        Raises `SiteInventoryNotFoundError` if nothing is stored under that
        exact tenant — a stored observation under a DIFFERENT tenant is
        indistinguishable from "never stored" to this caller, by design
        (never leak cross-tenant existence).
        """
        with self._lock:
            tenant_store = self._store.get(tenant_id, {})
            observation = tenant_store.get(site_id)
        if observation is None:
            raise SiteInventoryNotFoundError(
                "no site inventory observation stored for this tenant/site_id",
                context={"requested_tenant_id": tenant_id, "site_id": site_id},
            )
        return observation


__all__ = ["InMemorySiteInventoryStore"]
