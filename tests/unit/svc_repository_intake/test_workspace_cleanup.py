"""Mission item 8: partial intake cleanup on failure — no half-state.

Exercises the `WorkspaceStaging` lease directly across every distinct
failure gate, proving `perform_intake`'s `finally`-block release runs no
matter which check stops the run, and the run's own `run_id` gets a fresh
handle each attempt (no stale/reused lease)."""

from __future__ import annotations

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import (
    ContentHashMismatchError,
    ForbiddenUriError,
    SecretScanFailedError,
)


def test_workspace_released_on_every_failure_gate(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    kwargs = dict(
        job_context=job_context,
        hash_verifier=hash_verifier,
        secret_scanner=secret_scanner,
        manifest_store=manifest_store,
        audit_sink=audit_sink,
        workspace=workspace,
    )

    forbidden_uri_payload = build_snapshot_payload(
        snapshot_uri="git://source-host.example/acme-co/repo?token=leak"
    )
    with pytest.raises(ForbiddenUriError):
        perform_intake(payload=forbidden_uri_payload, **kwargs)
    assert workspace.outstanding == frozenset()

    hash_mismatch_payload = build_snapshot_payload(
        snapshot_uri="git://source-host.example/acme-co/other"
    )
    hash_verifier.mark_mismatch(hash_mismatch_payload["snapshot_uri"])
    with pytest.raises(ContentHashMismatchError):
        perform_intake(payload=hash_mismatch_payload, **kwargs)
    assert workspace.outstanding == frozenset()

    secret_payload = build_snapshot_payload(
        snapshot_uri="git://source-host.example/acme-co/flagged"
    )
    secret_scanner.flag(secret_payload["snapshot_uri"])
    with pytest.raises(SecretScanFailedError):
        perform_intake(payload=secret_payload, **kwargs)
    assert workspace.outstanding == frozenset()

    # exactly 3 acquire/release round-trips, all released, none stuck
    assert len(workspace._released) == 3  # noqa: SLF001 — white-box test assertion
