"""Factory helpers for `saena_artifact_registry` unit tests.

Deliberately NOT named `conftest.py` — see
`tests/unit/domain_persistence/persistence_factories.py`'s module docstring
for why a second `conftest.py` in a sibling test directory causes an import
collision when the full `tests/unit` suite is collected together. This
module is imported by its own unique dotted name (`registry_factories`,
inserted onto `sys.path` by this directory's `conftest.py`).
"""

from __future__ import annotations

import base64
from typing import Any

TENANT_A = "acme-co"
TENANT_B = "globex-co"

PATCH_UNIT_ID = "w2-16-artifact-registry"
WORKTREE_COMMIT = "9f1c2e7"


def build_manifest_fields(
    *,
    tenant_id: str = TENANT_A,
    run_id: str = "run-0001",
    patch_unit_id: str = PATCH_UNIT_ID,
    worktree_commit: str = WORKTREE_COMMIT,
) -> dict[str, Any]:
    """Return a valid `ArtifactManifestFields`-shaped payload (every
    `PatchArtifact` field except server-computed `artifact_hash`)."""
    return {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "patch_unit_id": patch_unit_id,
        "worktree_commit": worktree_commit,
        "base_commit": "a" * 40,
        "changed_files": ["src/module.py"],
        "quality_gate_ids": ["gate-lint", "gate-test"],
        "evidence_ids": ["evidence-0001"],
        "contract_hash": "sha256:" + "b" * 64,
        "rollback_ref": "rollback-ref-0001",
        "created_at": "2026-07-13T00:00:00Z",
    }


def encode_blob(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def build_register_request(
    *,
    blob: bytes = b"diff content bytes",
    manifest_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = build_manifest_fields()
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return {"manifest": manifest, "blob_base64": encode_blob(blob)}
