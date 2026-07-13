"""HTTP adapters wiring `saena_agent_runner`/`saena_quality_eval` to a REAL
`artifact-registry-service` FastAPI app (`fastapi.testclient.TestClient`
over the real ASGI app — same "why TestClient, not bare ASGITransport"
rationale as `tests/integration/approval_flow/approval_harness.py::
PlanContractHttpGateAdapter`).

Two adapters, two field-shape gaps this module bridges (glue code, not a
change to either service's exclusive-write path — reported, not patched):

- `HttpArtifactRegistryGateway` implements `saena_agent_runner.artifact.
  ArtifactRegistryGateway` (the `register()` Protocol `PatchUnitRunner`
  calls). GAP: `register()`'s own call signature (`tenant_id`, `run_id`,
  `patch_unit_id`, `worktree_commit`, `base_commit`, `changed_files`) does
  NOT carry `contract_hash`/`quality_gate_ids`/`evidence_ids`/
  `rollback_ref`/`created_at` — fields `artifact-registry-service`'s REAL
  `POST /v1/artifacts` manifest body requires (`ArtifactManifestFields`,
  `saena_artifact_registry.app`). `FakeArtifactRegistryGateway` never
  notices this gap (it fabricates an opaque ref and ignores those fields
  entirely) — a REAL adapter must source them some other way. This adapter
  takes them pre-bound per patch_unit_id at construction time (the SAME
  values `runner.py` itself will independently compute moments later from
  `contract.hypotheses`/`patch_unit.tests`/`patch_unit.rollback`/
  `clock.now_iso()`) rather than from `register()`'s own parameters.
- `HttpArtifactManifestPort` implements the READ half of `saena_domain.
  persistence.ports.ArtifactManifestPort` (only `.get()` — the method
  `saena_quality_eval.manifest.resolve_patch_artifact` actually calls) by
  querying the same real service's `GET /v1/artifacts/{patch_unit_id}/
  {worktree_commit}` route, so quality-eval's manifest-resolution step
  reads back the SAME real, server-computed manifest agent-runner's step
  registered — proving the two job kinds' handoff through
  artifact-registry-service is real, not two independently-fabricated
  fixtures that happen to share a name.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from saena_agent_runner.artifact import RegisteredArtifactRef
from saena_domain.identity import TenantId
from saena_domain.identity.http import TENANT_HEADER_NAME
from saena_domain.persistence.errors import NotFoundError, TenantIsolationError


@dataclass(frozen=True, slots=True)
class PatchUnitArtifactFacts:
    """The extra fields artifact-registry-service's real manifest contract
    needs, that `ArtifactRegistryGateway.register()`'s own signature does
    not carry (see module docstring GAP note)."""

    contract_hash: str
    quality_gate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    rollback_ref: str
    created_at: str


class HttpArtifactRegistryGateway:
    """Real `ArtifactRegistryGateway` — registers each committed patch
    unit's ACTUAL git diff bytes (computed lazily via a real `git diff
    <base_commit>..<worktree_commit>` call against the same synthetic repo
    `runner.py` just committed into — `worktree_commit` is only known AFTER
    `WorktreeHandle.commit()` runs, i.e. at `register()` call time, never
    before) against a real `artifact-registry-service` app."""

    def __init__(
        self,
        client: TestClient,
        *,
        facts_by_patch_unit_id: dict[str, PatchUnitArtifactFacts],
        diff_source: Any,
    ) -> None:
        self._client = client
        self._facts = facts_by_patch_unit_id
        # `diff_source` is a `GitSyntheticRepo`-shaped object exposing
        # `.unified_diff(base_commit, target_commit) -> bytes` (typed `Any`
        # here to avoid this test-harness module depending on
        # `git_worktree_adapter`'s concrete class — structural duck typing
        # only, mirroring this package's other Protocol-adapter discipline).
        self._diff_source = diff_source
        self.raw_responses: list[dict[str, Any]] = []

    def register(
        self,
        *,
        tenant_id: str,
        run_id: str,
        patch_unit_id: str,
        worktree_commit: str,
        base_commit: str,
        changed_files: list[str],
    ) -> RegisteredArtifactRef:
        facts = self._facts[patch_unit_id]
        diff_bytes = self._diff_source.unified_diff(base_commit, worktree_commit)
        manifest = {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "patch_unit_id": patch_unit_id,
            "worktree_commit": worktree_commit,
            "base_commit": base_commit,
            "changed_files": list(changed_files),
            "quality_gate_ids": list(facts.quality_gate_ids),
            "evidence_ids": list(facts.evidence_ids),
            "contract_hash": facts.contract_hash,
            "rollback_ref": facts.rollback_ref,
            "created_at": facts.created_at,
        }
        response = self._client.post(
            "/v1/artifacts",
            json={
                "manifest": manifest,
                "blob_base64": base64.b64encode(diff_bytes).decode("ascii"),
            },
            headers={TENANT_HEADER_NAME: tenant_id},
        )
        assert response.status_code in (200, 201), response.text
        body = response.json()
        self.raw_responses.append(body)
        stored = body["manifest"]
        return RegisteredArtifactRef(
            manifest_uri=stored["manifest_uri"],
            artifact_uri=stored["artifact_uri"],
            artifact_hash=stored["artifact_hash"],
        )

    def fetch_blob(self, *, tenant_id: str, patch_unit_id: str, worktree_commit: str) -> bytes:
        """Real gated blob fetch — used by tests to prove the registered
        diff bytes round-trip through the real blob single-gateway."""
        response = self._client.get(
            f"/v1/artifacts/{patch_unit_id}/{worktree_commit}/blob",
            headers={TENANT_HEADER_NAME: tenant_id},
        )
        assert response.status_code == 200, response.text
        return response.content


class HttpArtifactManifestPort:
    """Real `ArtifactManifestPort` read adapter — only `.get()` is
    implemented (the only method `saena_quality_eval.manifest.
    resolve_patch_artifact` calls); `.put()` is intentionally NOT
    implemented (agent-runner's step above already wrote the manifest via
    the real HTTP `POST /v1/artifacts` route — writing it a second time
    through a different path would defeat the single-gateway proof this
    adapter exists for)."""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def get(self, tenant_id: TenantId, patch_unit_id: str, worktree_commit: str) -> dict[str, Any]:
        response = self._client.get(
            f"/v1/artifacts/{patch_unit_id}/{worktree_commit}",
            headers={TENANT_HEADER_NAME: tenant_id.value},
        )
        if response.status_code == 404:
            raise NotFoundError(
                f"no artifact manifest for patch_unit_id={patch_unit_id!r} "
                f"worktree_commit={worktree_commit!r}",
                context={"patch_unit_id": patch_unit_id, "worktree_commit": worktree_commit},
            )
        if response.status_code == 403:
            raise TenantIsolationError(
                "artifact manifest does not belong to the requesting tenant",
                context={"patch_unit_id": patch_unit_id, "worktree_commit": worktree_commit},
            )
        assert response.status_code == 200, response.text
        return dict(response.json()["manifest"])


__all__ = [
    "HttpArtifactManifestPort",
    "HttpArtifactRegistryGateway",
    "PatchUnitArtifactFacts",
]
