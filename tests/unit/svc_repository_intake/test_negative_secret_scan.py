"""NEGATIVE TESTS: credential/secret in source (mission item 3) and
"scan-fail-then-attempt-execute (must stay blocked)"."""

from __future__ import annotations

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import IntakeManifestNotFoundError, SecretScanFailedError


def test_flagged_snapshot_is_refused_redacted_no_secret_echoed(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload()
    secret_scanner.flag(payload["snapshot_uri"])

    literal_secret = "AKIA_PLANTED_SECRET_VALUE_DO_NOT_ECHO"

    with pytest.raises(SecretScanFailedError) as excinfo:
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
    assert exc.error_code == "saena.policy_denied.secret_scan_failed"
    # redacted: no literal secret value ever appears in the exception, its
    # context, its JobError rendering, or the audit trail — the fake
    # SecretScanner deliberately never receives/returns `literal_secret` in
    # the first place, and this assertion proves it does not leak through
    # any of those surfaces even so.
    assert literal_secret not in str(exc)
    job_error = exc.to_job_error()
    assert literal_secret not in job_error.summary
    for value in job_error.redacted_detail.values():
        assert literal_secret not in value
    for event in audit_sink.events:
        assert literal_secret not in str(event)

    # refused -> never stored (no half-state)
    from saena_domain.identity import TenantId

    with pytest.raises(IntakeManifestNotFoundError):
        manifest_store.get(TenantId(job_context.tenant_id), payload["content_hash"])

    assert workspace.outstanding == frozenset()


def test_scan_fail_then_attempt_execute_stays_blocked(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    """After a secret-scan refusal, nothing was persisted; a repeat attempt
    against the same still-flagged snapshot must also stay refused — it can
    never accidentally "succeed" via an idempotent-replay shortcut, since no
    accepted manifest was ever stored to replay."""
    payload = build_snapshot_payload()
    secret_scanner.flag(payload["snapshot_uri"])
    kwargs = dict(
        job_context=job_context,
        hash_verifier=hash_verifier,
        secret_scanner=secret_scanner,
        manifest_store=manifest_store,
        audit_sink=audit_sink,
        workspace=workspace,
    )

    with pytest.raises(SecretScanFailedError):
        perform_intake(payload=payload, **kwargs)

    from saena_domain.identity import TenantId

    with pytest.raises(IntakeManifestNotFoundError):
        manifest_store.get(TenantId(job_context.tenant_id), payload["content_hash"])

    # second attempt ("execute") — must stay blocked, not silently proceed
    with pytest.raises(SecretScanFailedError):
        perform_intake(payload=dict(payload), **kwargs)

    with pytest.raises(IntakeManifestNotFoundError):
        manifest_store.get(TenantId(job_context.tenant_id), payload["content_hash"])

    decisions = [event["decision"] for event in audit_sink.events]
    assert decisions == ["refused", "refused"]
    assert workspace.outstanding == frozenset()
