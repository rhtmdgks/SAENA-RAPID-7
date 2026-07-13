"""Patch artifact reference resolution — mission item 1, "Consume a patch
artifact reference (by manifest ref)".

`resolve_patch_artifact` is the ONLY place in this package that talks to a
`saena_domain.persistence.ArtifactManifestPort` (the artifact-registry-owned
manifest store, contract-catalog.md P0 row "PatchArtifact") — everywhere
else in this package takes an already-resolved, already-validated
`PatchArtifact` dict, keeping the gate engine itself storage-agnostic (a
future real deployment wires a real `ArtifactManifestPort` adapter here;
unit tests use `saena_domain.persistence.InMemoryArtifactManifestStore`,
which this module is written against structurally — any `ArtifactManifestPort`
implementation works).

The resolved manifest is validated against the `domain/patch-artifact/v1`
contract's generated pydantic model (`saena_schemas.domain.patch_artifact_v1.
PatchArtifact`) before this module hands it back — a manifest stored under
the ref that does not itself conform to that CLOSED contract is a hard
`PatchArtifactReferenceError`, never silently passed through to the gate
engine.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from saena_domain.identity import TenantId
from saena_domain.persistence.errors import NotFoundError, TenantIsolationError
from saena_domain.persistence.ports import ArtifactManifestPort
from saena_schemas.domain.patch_artifact_v1 import PatchArtifact

from saena_quality_eval.errors import PatchArtifactReferenceError


def resolve_patch_artifact(
    manifest_port: ArtifactManifestPort,
    *,
    tenant_id: TenantId,
    patch_unit_id: str,
    worktree_commit: str,
) -> dict[str, Any]:
    """Resolve a `(patch_unit_id, worktree_commit)` manifest ref into a
    contract-validated `PatchArtifact` dict.

    Raises `PatchArtifactReferenceError` if no manifest is stored under the
    ref, the ref belongs to a different tenant, or the stored manifest does
    not conform to `domain/patch-artifact/v1`.
    """
    try:
        manifest = manifest_port.get(tenant_id, patch_unit_id, worktree_commit)
    except NotFoundError as exc:
        raise PatchArtifactReferenceError(
            f"no PatchArtifact manifest stored for patch_unit_id={patch_unit_id!r} "
            f"worktree_commit={worktree_commit!r}",
            context={"patch_unit_id": patch_unit_id, "worktree_commit": worktree_commit},
        ) from exc
    except TenantIsolationError as exc:
        raise PatchArtifactReferenceError(
            "patch artifact manifest ref does not belong to the requesting tenant",
            context={"patch_unit_id": patch_unit_id, "worktree_commit": worktree_commit},
        ) from exc

    try:
        model = PatchArtifact.model_validate(manifest)
    except ValidationError as exc:
        raise PatchArtifactReferenceError(
            "resolved PatchArtifact manifest does not conform to domain/patch-artifact/v1",
            context={"patch_unit_id": patch_unit_id, "worktree_commit": worktree_commit},
        ) from exc
    return model.model_dump(mode="json")


__all__ = ["resolve_patch_artifact"]
