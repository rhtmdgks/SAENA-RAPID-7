"""Proof-carrying `PatchArtifact` construction — manifest-ref only."""

from __future__ import annotations

import pytest
from runner_factories import BASE_COMMIT, CONTRACT_HASH, PATCH_UNIT_ID, RUN_ID, TENANT_A
from saena_agent_runner.artifact import FakeArtifactRegistryGateway, build_patch_artifact
from saena_agent_runner.errors import ContractValidationError


def test_fake_gateway_never_returns_a_resolvable_storage_url() -> None:
    gateway = FakeArtifactRegistryGateway()
    ref = gateway.register(
        tenant_id=TENANT_A,
        run_id=RUN_ID,
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="deadbeef",
        base_commit=BASE_COMMIT,
        changed_files=["a.txt"],
    )
    # Opaque scheme://tenant/hash shape only — never a presigned token/query string.
    assert ref.artifact_uri.startswith("blob://")
    assert "?" not in ref.artifact_uri
    assert ref.manifest_uri.startswith("manifest://")
    assert ref.artifact_hash.startswith("sha256:")
    assert len(gateway.registrations) == 1


def test_build_patch_artifact_produces_schema_valid_dict() -> None:
    gateway = FakeArtifactRegistryGateway()
    ref = gateway.register(
        tenant_id=TENANT_A,
        run_id=RUN_ID,
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="deadbeef",
        base_commit=BASE_COMMIT,
        changed_files=["a.txt"],
    )
    artifact = build_patch_artifact(
        tenant_id=TENANT_A,
        run_id=RUN_ID,
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="deadbeef",
        base_commit=BASE_COMMIT,
        changed_files=["a.txt"],
        quality_gate_ids=["test-01"],
        evidence_ids=["EV-01"],
        contract_hash=CONTRACT_HASH,
        rollback_ref=f"git-revert:{PATCH_UNIT_ID}",
        created_at="2026-07-13T00:00:00Z",
        registered_ref=ref,
    )
    assert artifact["tenant_id"] == TENANT_A
    assert artifact["patch_unit_id"] == PATCH_UNIT_ID
    assert artifact["worktree_commit"] == "deadbeef"
    assert artifact["artifact_uri"] == ref.artifact_uri
    assert artifact["manifest_uri"] == ref.manifest_uri


def test_build_patch_artifact_rejects_malformed_worktree_commit() -> None:
    gateway = FakeArtifactRegistryGateway()
    ref = gateway.register(
        tenant_id=TENANT_A,
        run_id=RUN_ID,
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="not-hex!!",
        base_commit=BASE_COMMIT,
        changed_files=["a.txt"],
    )
    with pytest.raises(ContractValidationError):
        build_patch_artifact(
            tenant_id=TENANT_A,
            run_id=RUN_ID,
            patch_unit_id=PATCH_UNIT_ID,
            worktree_commit="not-hex!!",
            base_commit=BASE_COMMIT,
            changed_files=["a.txt"],
            quality_gate_ids=["test-01"],
            evidence_ids=["EV-01"],
            contract_hash=CONTRACT_HASH,
            rollback_ref=f"git-revert:{PATCH_UNIT_ID}",
            created_at="2026-07-13T00:00:00Z",
            registered_ref=ref,
        )
