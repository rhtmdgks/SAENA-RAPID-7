"""`manifest.resolve_patch_artifact` / `contract.extract_approved_contract_facts`
— mission item 1 ("Consume a patch artifact reference (by manifest ref) + the
approved contract")."""

from __future__ import annotations

import pytest
from factories import BASE_COMMIT, PATCH_UNIT_ID, WORKTREE_COMMIT, build_patch_artifact_manifest
from saena_domain.identity import TenantId
from saena_quality_eval.contract import extract_approved_contract_facts
from saena_quality_eval.errors import ApprovedContractValidationError, PatchArtifactReferenceError
from saena_quality_eval.manifest import resolve_patch_artifact


def test_resolve_patch_artifact_round_trips_through_the_manifest_port(
    manifest_store, patch_artifact_manifest, tenant_id
) -> None:
    manifest_store.put(TenantId(tenant_id), PATCH_UNIT_ID, WORKTREE_COMMIT, patch_artifact_manifest)
    resolved = resolve_patch_artifact(
        manifest_store,
        tenant_id=TenantId(tenant_id),
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit=WORKTREE_COMMIT,
    )
    assert resolved["patch_unit_id"] == PATCH_UNIT_ID
    assert resolved["base_commit"] == BASE_COMMIT


def test_resolve_patch_artifact_raises_on_unknown_ref(manifest_store, tenant_id) -> None:
    with pytest.raises(PatchArtifactReferenceError):
        resolve_patch_artifact(
            manifest_store,
            tenant_id=TenantId(tenant_id),
            patch_unit_id="does-not-exist",
            worktree_commit=WORKTREE_COMMIT,
        )


def test_resolve_patch_artifact_raises_on_cross_tenant_ref(
    manifest_store, patch_artifact_manifest, tenant_id
) -> None:
    manifest_store.put(TenantId(tenant_id), PATCH_UNIT_ID, WORKTREE_COMMIT, patch_artifact_manifest)
    with pytest.raises(PatchArtifactReferenceError):
        resolve_patch_artifact(
            manifest_store,
            tenant_id=TenantId("other-tenant"),
            patch_unit_id=PATCH_UNIT_ID,
            worktree_commit=WORKTREE_COMMIT,
        )


def test_resolve_patch_artifact_rejects_a_manifest_not_conforming_to_the_contract(
    manifest_store, tenant_id
) -> None:
    bad_manifest = build_patch_artifact_manifest()
    del bad_manifest["evidence_ids"]  # required field
    manifest_store.put(TenantId(tenant_id), PATCH_UNIT_ID, WORKTREE_COMMIT, bad_manifest)
    with pytest.raises(PatchArtifactReferenceError):
        resolve_patch_artifact(
            manifest_store,
            tenant_id=TenantId(tenant_id),
            patch_unit_id=PATCH_UNIT_ID,
            worktree_commit=WORKTREE_COMMIT,
        )


def test_extract_approved_contract_facts(approved_change_plan) -> None:
    facts = extract_approved_contract_facts(approved_change_plan)
    assert facts.approved_base_commit == BASE_COMMIT
    assert facts.approved_patch_unit_ids == frozenset({PATCH_UNIT_ID})
    assert facts.approved_scope_globs == ("apps/web/*",)


def test_extract_approved_contract_facts_rejects_malformed_contract(approved_change_plan) -> None:
    del approved_change_plan["patch_units"]
    with pytest.raises(ApprovedContractValidationError):
        extract_approved_contract_facts(approved_change_plan)
