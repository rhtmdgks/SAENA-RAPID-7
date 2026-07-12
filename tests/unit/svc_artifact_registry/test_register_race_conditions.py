"""`register_artifact`'s pre-`put()` existence check and the `put()` call
itself are two separate port calls (see `app.py`'s "Determine fresh-insert
vs. idempotent-replay BEFORE calling put()" comment) — a
`TenantIsolationError` raised specifically by the `put()` call (as opposed
to the pre-check `get()` call) is only reachable if the underlying store's
state changes between the two calls. This module exercises that branch via
a thin wrapper port that forces exactly that race."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from registry_factories import build_register_request
from saena_artifact_registry import InMemoryBlobStore, create_app
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryArtifactManifestStore, TenantIsolationError


class _PutRacesTenantIsolationPort:
    """Wraps a real `InMemoryArtifactManifestStore`; `get()` behaves
    normally (so the pre-check sees "not found" and proceeds), but `put()`
    always raises `TenantIsolationError` — simulating another tenant
    claiming the same key between this handler's `get()` and `put()` calls."""

    def __init__(self, inner: InMemoryArtifactManifestStore) -> None:
        self._inner = inner

    def get(self, tenant_id: TenantId, patch_unit_id: str, worktree_commit: str) -> dict[str, Any]:
        return self._inner.get(tenant_id, patch_unit_id, worktree_commit)

    def put(
        self,
        tenant_id: TenantId,
        patch_unit_id: str,
        worktree_commit: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        raise TenantIsolationError(
            "simulated race: another tenant claimed this key between get() and put()",
            context={"patch_unit_id": patch_unit_id},
        )


@pytest.fixture
def racing_client(tenant_headers: dict[str, str]) -> TestClient:
    racing_port = _PutRacesTenantIsolationPort(InMemoryArtifactManifestStore())
    app = create_app(racing_port, InMemoryBlobStore())  # type: ignore[arg-type]
    return TestClient(app)


def test_put_time_tenant_isolation_error_maps_to_404(
    racing_client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = racing_client.post(
        "/v1/artifacts", json=build_register_request(), headers=tenant_headers
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.artifact_manifest"
