"""Happy-path intake: accepted decision, immutable manifest, repo.intaken.v1
event payload, audit event recorded, workspace released."""

from __future__ import annotations

import dataclasses

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import IntakeDecision, perform_intake
from saena_repository_intake.errors import RepositoryIntakeError


def test_accepted_intake_builds_immutable_manifest_and_event(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload()

    outcome = perform_intake(
        payload=payload,
        job_context=job_context,
        hash_verifier=hash_verifier,
        secret_scanner=secret_scanner,
        manifest_store=manifest_store,
        audit_sink=audit_sink,
        workspace=workspace,
    )

    assert outcome.replayed is False
    assert outcome.manifest.decision == IntakeDecision.ACCEPTED
    assert outcome.manifest.secret_scan_status == "passed"
    assert outcome.manifest.content_hash == payload["content_hash"]
    assert outcome.manifest.repo_commit == payload["repo_commit"]

    # immutable: frozen dataclass rejects reassignment
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.manifest.repo_commit = "z" * 40  # type: ignore[misc]

    # repo.intaken.v1 payload — never carries file listings/content, only refs
    assert outcome.event_payload["repo_commit"] == payload["repo_commit"]
    assert outcome.event_payload["content_hash"] == payload["content_hash"]
    assert set(outcome.event_payload.keys()) <= {"repo_commit", "content_hash", "snapshot_uri"}

    # persisted, retrievable via the port
    from saena_domain.identity import TenantId

    stored = manifest_store.get(TenantId(job_context.tenant_id), payload["content_hash"])
    assert stored["decision"] == "accepted"

    # audit event recorded for the decision (mission item 11)
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0]["decision"] == "accepted"
    assert audit_sink.events[0]["content_hash"] == payload["content_hash"]

    # workspace lease acquired and released exactly once, no leak
    assert workspace.outstanding == frozenset()


def test_accept_rejects_unknown_kwargs_defensively(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    """Sanity: an intake payload missing a required field is a structural
    refusal, not a silent partial accept."""
    payload = build_snapshot_payload()
    del payload["sbom_uri"]

    with pytest.raises(RepositoryIntakeError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )
    assert excinfo.value.error_code == "saena.validation.malformed_intake_request"
    assert workspace.outstanding == frozenset()
