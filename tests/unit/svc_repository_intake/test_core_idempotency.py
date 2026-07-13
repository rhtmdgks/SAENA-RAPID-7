"""Duplicate intake idempotency (mission item 7): same content_hash resend
with identical fields is a no-op replay (no double effect); a resend under
the same content_hash with DIFFERENT identifying fields is a hard conflict
(NEGATIVE TEST: "resend/duplicate conflict")."""

from __future__ import annotations

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import DuplicateIntakeConflictError


def test_identical_resend_is_idempotent_replay_no_double_effect(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload()
    kwargs = dict(
        job_context=job_context,
        hash_verifier=hash_verifier,
        secret_scanner=secret_scanner,
        manifest_store=manifest_store,
        audit_sink=audit_sink,
        workspace=workspace,
    )

    first = perform_intake(payload=payload, **kwargs)
    second = perform_intake(payload=dict(payload), **kwargs)

    assert first.replayed is False
    assert second.replayed is True
    assert first.manifest == second.manifest
    assert second.event_payload == first.event_payload

    # exactly one manifest ever stored under this key — no double effect
    from saena_domain.identity import TenantId

    tenant_id = TenantId(job_context.tenant_id)
    stored = manifest_store.get(tenant_id, payload["content_hash"])
    assert stored["decision"] == "accepted"

    # two decisions audited: one accepted, one replayed — never two accepts
    decisions = [event["decision"] for event in audit_sink.events]
    assert decisions == ["accepted", "replayed"]

    assert workspace.outstanding == frozenset()


def test_resend_with_different_content_under_same_hash_is_conflict(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload()
    kwargs = dict(
        job_context=job_context,
        hash_verifier=hash_verifier,
        secret_scanner=secret_scanner,
        manifest_store=manifest_store,
        audit_sink=audit_sink,
        workspace=workspace,
    )
    perform_intake(payload=payload, **kwargs)

    conflicting = dict(payload)
    conflicting["snapshot_uri"] = "git://source-host.example/acme-co/other-repo"

    with pytest.raises(DuplicateIntakeConflictError) as excinfo:
        perform_intake(payload=conflicting, **kwargs)

    assert excinfo.value.error_code == "saena.conflict.duplicate_intake"
    assert workspace.outstanding == frozenset()

    # the original accepted manifest is untouched by the rejected conflict
    from saena_domain.identity import TenantId

    stored = manifest_store.get(TenantId(job_context.tenant_id), payload["content_hash"])
    assert stored["snapshot_uri"] == payload["snapshot_uri"]
