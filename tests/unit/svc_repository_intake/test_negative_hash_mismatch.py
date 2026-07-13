"""NEGATIVE TEST: content hash mismatch (mission item 2)."""

from __future__ import annotations

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import ContentHashMismatchError, IntakeManifestNotFoundError


def test_hash_mismatch_is_refused(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload()
    hash_verifier.mark_mismatch(payload["snapshot_uri"])

    with pytest.raises(ContentHashMismatchError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

    assert excinfo.value.error_code == "saena.validation.content_hash_mismatch"

    from saena_domain.identity import TenantId

    with pytest.raises(IntakeManifestNotFoundError):
        manifest_store.get(TenantId(job_context.tenant_id), payload["content_hash"])

    assert audit_sink.events[-1]["decision"] == "refused"
    assert workspace.outstanding == frozenset()
