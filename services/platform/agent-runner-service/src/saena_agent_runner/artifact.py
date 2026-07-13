"""Proof-carrying `PatchArtifact` construction — manifest-ref only, never a
direct blob write.

`docs/architecture/data-ownership.md` ("manifest = artifact-registry, blob
쓰기 단일 관문 = artifact-registry") and this package's own mission
instruction ("reference blobs only by manifest ref ... never direct blob
write — artifact-registry owns that gateway"): `saena_agent_runner` NEVER
constructs a `BlobRef`/talks to object storage itself. `ArtifactRegistryGateway`
is the injected Protocol boundary — a real adapter (calling
`artifact-registry-service`'s published HTTP contract) is a later, separate
concern; this package only defines the call SHAPE and ships an in-memory
fake for its own unit tests, mirroring
`services/platform/agent-orchestrator-service/activities.py`'s own
blob-single-gateway discipline (`manifest_ref`-only Activity input).

Reuses the generated `saena_schemas.domain.patch_artifact_v1.PatchArtifact`
pydantic model to validate the assembled artifact dict before it is ever
handed back to a caller — a `PatchArtifact` this package builds is always
schema-valid by construction.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError
from saena_schemas.domain.patch_artifact_v1 import PatchArtifact

from saena_agent_runner.errors import ContractValidationError


@dataclass(frozen=True, slots=True)
class RegisteredArtifactRef:
    """Opaque references an `ArtifactRegistryGateway.register` call returns.

    Never a resolvable storage URL/presigned token (same discipline as
    `saena_artifact_registry.blobstore.BlobRef` — this package does not
    itself parse/interpret these strings beyond passing them through
    `PatchArtifact.artifact_uri`/`.manifest_uri`, which validates their
    `scheme://...` shape)."""

    manifest_uri: str
    artifact_uri: str
    artifact_hash: str


@runtime_checkable
class ArtifactRegistryGateway(Protocol):
    """Single-gateway boundary this package delegates ALL blob storage to.

    `runner.py` calls this once per successfully-committed patch unit,
    AFTER `WorktreeHandle.commit()` has already produced a real
    `worktree_commit` — this Protocol never sees uncommitted/rolled-back
    state.
    """

    def register(
        self,
        *,
        tenant_id: str,
        run_id: str,
        patch_unit_id: str,
        worktree_commit: str,
        base_commit: str,
        changed_files: Sequence[str],
    ) -> RegisteredArtifactRef:
        """Register the diff/manifest for one committed patch unit.

        Returns the opaque refs `build_patch_artifact` assembles into a
        full `PatchArtifact`. Implementations own actual blob storage
        (out of this package's scope) — this call is a black box from
        `saena_agent_runner`'s point of view.
        """
        ...


class FakeArtifactRegistryGateway:
    """Reference `ArtifactRegistryGateway` — deterministic opaque refs, no
    real blob storage, no network call. Records every registration for
    test assertions."""

    def __init__(self) -> None:
        self.registrations: list[dict[str, Any]] = []

    def register(
        self,
        *,
        tenant_id: str,
        run_id: str,
        patch_unit_id: str,
        worktree_commit: str,
        base_commit: str,
        changed_files: Sequence[str],
    ) -> RegisteredArtifactRef:
        self.registrations.append(
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "patch_unit_id": patch_unit_id,
                "worktree_commit": worktree_commit,
                "base_commit": base_commit,
                "changed_files": list(changed_files),
            }
        )
        digest_source = "|".join(
            [tenant_id, patch_unit_id, worktree_commit, *sorted(changed_files)]
        )
        content_hash = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
        return RegisteredArtifactRef(
            manifest_uri=f"manifest://{tenant_id}/{patch_unit_id}/{worktree_commit}",
            artifact_uri=f"blob://{tenant_id}/{content_hash}",
            artifact_hash=f"sha256:{content_hash}",
        )


def build_patch_artifact(
    *,
    tenant_id: str,
    run_id: str,
    patch_unit_id: str,
    worktree_commit: str,
    base_commit: str,
    changed_files: Sequence[str],
    quality_gate_ids: Sequence[str],
    evidence_ids: Sequence[str],
    contract_hash: str,
    rollback_ref: str,
    created_at: str,
    registered_ref: RegisteredArtifactRef,
) -> dict[str, Any]:
    """Assemble + validate a proof-carrying `PatchArtifact` dict.

    `registered_ref` is the gateway's own output — this function never
    computes `artifact_uri`/`artifact_hash`/`manifest_uri` itself (single
    blob-gateway invariant). Raises `ContractValidationError` if the
    assembled dict fails the closed `PatchArtifact` schema (e.g. a
    malformed `worktree_commit`/`contract_hash` shape).
    """
    candidate: dict[str, Any] = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "patch_unit_id": patch_unit_id,
        "worktree_commit": worktree_commit,
        "base_commit": base_commit,
        "artifact_uri": registered_ref.artifact_uri,
        "artifact_hash": registered_ref.artifact_hash,
        "manifest_uri": registered_ref.manifest_uri,
        "changed_files": list(changed_files),
        "quality_gate_ids": list(quality_gate_ids),
        "evidence_ids": list(evidence_ids),
        "contract_hash": contract_hash,
        "rollback_ref": rollback_ref,
        "created_at": created_at,
    }
    try:
        validated = PatchArtifact.model_validate(candidate)
    except ValidationError as exc:
        raise ContractValidationError(
            f"assembled PatchArtifact failed schema validation: {exc}", context={}
        ) from exc
    return validated.model_dump(mode="json")


__all__ = [
    "ArtifactRegistryGateway",
    "FakeArtifactRegistryGateway",
    "RegisteredArtifactRef",
    "build_patch_artifact",
]
