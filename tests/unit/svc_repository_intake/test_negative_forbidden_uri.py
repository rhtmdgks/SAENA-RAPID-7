"""NEGATIVE TEST: forbidden-URI-with-query (ADR-0024(f) R9-5) and a
disallowed scheme (mission item 9)."""

from __future__ import annotations

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import ForbiddenUriError


def test_snapshot_uri_with_query_string_is_forbidden(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload(
        snapshot_uri="git://source-host.example/acme-co/repo?X-Amz-Signature=leaked-token"
    )

    with pytest.raises(ForbiddenUriError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

    assert excinfo.value.error_code == "saena.validation.forbidden_source_uri"
    assert excinfo.value.context["field"] == "snapshot_uri"
    assert workspace.outstanding == frozenset()


def test_snapshot_uri_with_disallowed_scheme_is_forbidden(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload(snapshot_uri="ftp://source-host.example/acme-co/repo")

    with pytest.raises(ForbiddenUriError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

    assert excinfo.value.context["scheme"] == "ftp"
    assert workspace.outstanding == frozenset()
