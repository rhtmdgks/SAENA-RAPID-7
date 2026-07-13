"""`InMemoryObservationStore` — tenant-scoped, in-memory observation store.

Same tenant-gate discipline as `saena_site_discovery.store.
InMemorySiteInventoryStore` (that module's docstring applies verbatim,
substituting `PlatformObservation` for `SiteInventoryObservation` and
`(tenant_id, run_id, query_text)` for `(tenant_id, site_id)` as the storage
key) — reference in-memory adapter for this unit's own tests only.
"""

from __future__ import annotations

import threading

from saena_chatgpt_observer.errors import CrossTenantObservationError, ObservationNotFoundError
from saena_chatgpt_observer.observation import PlatformObservation


class InMemoryObservationStore:
    """Pure-Python, tenant-scoped `PlatformObservation` store, keyed by
    `(tenant_id, run_id, query_text)`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[tuple[str, str], PlatformObservation]] = {}

    def put(self, tenant_id: str, observation: PlatformObservation) -> PlatformObservation:
        """Store `observation`, keyed under `tenant_id` by
        `(run_id, query_text)`.

        Raises `CrossTenantObservationError` if `observation.tenant_id !=
        tenant_id`.
        """
        if observation.tenant_id != tenant_id:
            raise CrossTenantObservationError(
                "observation.tenant_id does not match the storing tenant_id",
                context={"requested_tenant_id": tenant_id},
            )
        with self._lock:
            self._store.setdefault(tenant_id, {})[(observation.run_id, observation.query_text)] = (
                observation
            )
        return observation

    def get(self, tenant_id: str, run_id: str, query_text: str) -> PlatformObservation:
        """Return the stored observation for `(tenant_id, run_id,
        query_text)`.

        Raises `ObservationNotFoundError` if nothing is stored under that
        exact tenant — a stored observation under a DIFFERENT tenant is
        indistinguishable from "never stored" to this caller, by design.
        """
        with self._lock:
            tenant_store = self._store.get(tenant_id, {})
            observation = tenant_store.get((run_id, query_text))
        if observation is None:
            raise ObservationNotFoundError(
                "no platform observation stored for this tenant/run_id/query_text",
                context={"requested_tenant_id": tenant_id, "run_id": run_id},
            )
        return observation


__all__ = ["InMemoryObservationStore"]
