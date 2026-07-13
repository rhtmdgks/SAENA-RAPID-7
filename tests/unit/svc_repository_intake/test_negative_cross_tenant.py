"""NEGATIVE TEST: cross-tenant source — snapshot's own tenant_id disagrees
with the authenticated JobContext.tenant_id (mission item 10)."""

from __future__ import annotations

import pytest
from intake_factories import TENANT_A, TENANT_B, build_job_context, build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import CrossTenantSourceError


def test_cross_tenant_source_is_refused_and_audited(
    manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    job_context = build_job_context(tenant_id=TENANT_A)
    payload = build_snapshot_payload(tenant_id=TENANT_B)  # snapshot claims a DIFFERENT tenant

    with pytest.raises(CrossTenantSourceError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

    exc = excinfo.value
    assert exc.error_code == "saena.policy_denied.cross_tenant_source"
    assert exc.context["snapshot_tenant_id"] == TENANT_B
    assert exc.context["job_context_tenant_id"] == TENANT_A

    # JobError conversion (mission: "refused ... with a JobError")
    job_error = exc.to_job_error()
    assert job_error.error_code == exc.error_code
    assert job_error.retryable is False

    # refused, never stored, and stopped before any tenant B content was touched
    from saena_domain.identity import TenantId
    from saena_repository_intake.errors import IntakeManifestNotFoundError

    with pytest.raises(IntakeManifestNotFoundError):
        manifest_store.get(TenantId(TENANT_A), payload["content_hash"])

    assert len(audit_sink.events) == 1
    assert audit_sink.events[0]["decision"] == "refused"
    assert audit_sink.events[0]["error_code"] == "saena.policy_denied.cross_tenant_source"

    # workspace lease still cleaned up on this refusal path
    assert workspace.outstanding == frozenset()
